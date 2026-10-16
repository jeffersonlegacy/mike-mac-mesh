from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .council import council_member
from .council_state import (
    apply_turn_patch,
    build_initial_council_state,
    handoff_summary,
    parse_structured_turn,
    render_synthesis_markdown,
    render_turn_markdown,
    state_context_text,
)
from .ledger import append_jsonl, now_iso, write_json

MAX_TRANSCRIPT_CONTEXT_CHARS = 4000
OPENCLAW_AGENTS_ROOT = Path.home() / ".openclaw" / "agents"
OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"


def _transcript_tail(text: str) -> str:
    if len(text) <= MAX_TRANSCRIPT_CONTEXT_CHARS:
        return text
    return text[-MAX_TRANSCRIPT_CONTEXT_CHARS:]


def _prompt_for_agent(
    *,
    agent_id: str,
    task_id: str,
    request_text: str,
    route: dict[str, Any],
    council_state: dict[str, Any],
) -> str:
    member = council_member(agent_id)
    state_tail = _transcript_tail(state_context_text(council_state, max_chars=MAX_TRANSCRIPT_CONTEXT_CHARS)).strip()
    return f"""Task ID: {task_id}

You are {member.name}, the {member.title} in the Agora council.
Mandate: {member.mandate}
Style: {member.style}

Original request:
{request_text}

Route:
- Chair: {route["chair"]}
- Planning lead: {route["planning_lead"]}
- Review lead: {route["review_lead"]}
- Council order: {" -> ".join(route["council_order"])}
- Verification: {route["verification"]}

Current council state JSON:
{state_tail}

Respond with valid JSON only. Do not wrap it in markdown fences.
Use this exact shape:
{{
  "position": "short role framing",
  "key_point": "main contribution",
  "risk": "main concern",
  "next_move": "best immediate next step",
  "confidence": 0,
  "state_patch": {{
    "win_condition": "",
    "minimum_viable_context": [],
    "momentum_vector": "",
    "asymmetric_leverage": "",
    "leverage_patch": "",
    "execution_guidance": "",
    "invariants": [],
    "invariant_check": {{
      "status": "pending|pass|review|halt",
      "notes": []
    }},
    "hard_halt": false,
    "decision": {{
      "verdict": "pending|ship|revise|halt",
      "summary": "",
      "next_action": ""
    }}
  }}
}}

Fill only the fields your role can improve. Use empty strings or empty arrays for untouched fields.
"""


def _parse_agent_output(stdout: str) -> tuple[str, dict[str, Any]]:
    raw = stdout.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
        for marker in ("\n{", "\n[", "{", "["):
            start = raw.find(marker)
            while start != -1:
                candidate = raw[start + (1 if marker.startswith("\n") else 0) :].strip()
                try:
                    payload = json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    start = raw.find(marker, start + 1)
            if payload is not None:
                break
        if payload is None:
            raise
    items = payload.get("payloads") if isinstance(payload.get("payloads"), list) else []
    text_chunks = [str(item.get("text") or "").strip() for item in items if str(item.get("text") or "").strip()]
    return ("\n\n".join(text_chunks).strip(), payload.get("meta") if isinstance(payload.get("meta"), dict) else {})


def _expected_provider_for_agent(agent_id: str) -> str | None:
    if not OPENCLAW_CONFIG_PATH.exists():
        return None
    try:
        payload = json.loads(OPENCLAW_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    agents = payload.get("agents", {}).get("list", [])
    if not isinstance(agents, list):
        return None
    for agent in agents:
        if not isinstance(agent, dict) or agent.get("id") != agent_id:
            continue
        model = agent.get("model")
        if isinstance(model, dict):
            primary = model.get("primary")
            if isinstance(primary, str) and "/" in primary:
                return primary.split("/", 1)[0]
        if isinstance(model, str) and "/" in model:
            return model.split("/", 1)[0]
        return None
    return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _ensure_agent_lane_available(agent_id: str) -> None:
    sessions_root = OPENCLAW_AGENTS_ROOT / agent_id / "sessions"
    if not sessions_root.exists():
        return
    for lock_path in sessions_root.glob("*.lock"):
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        pid = payload.get("pid")
        if isinstance(pid, int) and _pid_running(pid):
            raise RuntimeError(f"council agent {agent_id} is busy: pid={pid} lock={lock_path}")
        lock_path.unlink(missing_ok=True)


def run_council_session(
    *,
    task_id: str,
    request_text: str,
    route: dict[str, Any],
    files: dict[str, Path],
    agent_ids: list[str],
    timeout: int = 180,
) -> dict[str, Any]:
    turns: list[dict[str, Any]] = []
    council_state = build_initial_council_state(
        task_id=task_id,
        request_text=request_text,
        route=route,
        agent_ids=agent_ids,
    )
    transcript_parts = [
        "# Council Transcript",
        "",
        f"Task ID: `{task_id}`",
        f"Started: `{now_iso()}`",
        "",
    ]

    for agent_id in agent_ids:
        member = council_member(agent_id)
        session_id = f"{task_id}-{agent_id}"
        _ensure_agent_lane_available(agent_id)
        prompt = _prompt_for_agent(
            agent_id=agent_id,
            task_id=task_id,
            request_text=request_text,
            route=route,
            council_state=council_state,
        )
        completed = subprocess.run(
            [
                "openclaw",
                "agent",
                "--agent",
                agent_id,
                "--local",
                "--session-id",
                session_id,
                "--timeout",
                str(timeout),
                "--message",
                prompt,
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip() or f"agent {agent_id} failed"
            raise RuntimeError(detail)

        response_text, meta = _parse_agent_output(completed.stdout)
        if response_text.strip().lower() == "this operation was aborted":
            raise RuntimeError(f"council agent {agent_id} aborted its turn")
        structured = parse_structured_turn(response_text)
        turn = {
            "agent": agent_id,
            "name": member.name,
            "session_id": session_id,
            "response": response_text,
            "duration_ms": meta.get("durationMs"),
            "provider": (meta.get("agentMeta") or {}).get("provider"),
            "model": (meta.get("agentMeta") or {}).get("model"),
            "structured": structured,
        }
        expected_provider = _expected_provider_for_agent(agent_id)
        actual_provider = turn["provider"]
        if not response_text.strip():
            raise RuntimeError(
                f"council agent {agent_id} returned no text via provider={actual_provider or 'unknown'} model={turn['model'] or 'unknown'}"
            )
        if expected_provider and actual_provider and actual_provider != expected_provider:
            raise RuntimeError(
                f"council agent {agent_id} fell back from {expected_provider} to {actual_provider}"
            )
        turns.append(turn)
        council_state = apply_turn_patch(council_state, turn)
        files["council_state"].write_text(
            f"{json.dumps(council_state, indent=2, sort_keys=False)}\n",
            encoding="utf-8",
        )
        checkpoint_path = files["council_checkpoints"] / f"{len(turns):02d}-{agent_id}.json"
        write_json(checkpoint_path, council_state)
        append_jsonl(
            files["events"],
            {
                "at": now_iso(),
                "event": "council.turn.completed",
                "payload": {
                    "agent": agent_id,
                    "duration_ms": turn["duration_ms"],
                    "provider": turn["provider"],
                    "model": turn["model"],
                    "checkpoint": str(checkpoint_path),
                    "handoff": handoff_summary(council_state.get("handoff")),
                },
            },
        )

        assignment_path = files[agent_id]
        existing = assignment_path.read_text(encoding="utf-8") if assignment_path.exists() else ""
        assignment_path.write_text(
            "\n".join(
                [
                    existing.rstrip(),
                    "",
                    "## Council Response",
                    "",
                    render_turn_markdown(turn),
                    "",
                ]
            ).lstrip(),
            encoding="utf-8",
        )

        transcript_parts.extend(
            [
                f"## {member.name}",
                "",
                render_turn_markdown(turn),
                "",
            ]
        )

    transcript_path = files["transcript"]
    transcript_path.write_text("\n".join(transcript_parts).rstrip() + "\n", encoding="utf-8")
    files["council_state"].write_text(
        f"{json.dumps(council_state, indent=2, sort_keys=False)}\n",
        encoding="utf-8",
    )
    files["synthesis"].write_text(render_synthesis_markdown(council_state), encoding="utf-8")
    return {
        "task_id": task_id,
        "order": agent_ids,
        "turns": turns,
        "transcript_path": str(transcript_path),
        "council_state_path": str(files["council_state"]),
        "council_state": council_state,
    }
