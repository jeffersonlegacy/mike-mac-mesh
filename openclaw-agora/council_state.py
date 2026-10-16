from __future__ import annotations

import json
from typing import Any


INVARIANT_STATUS_ORDER = {
    "pending": 0,
    "pass": 1,
    "review": 2,
    "halt": 3,
}

DECISION_VERDICTS = {"pending", "ship", "revise", "halt"}


def build_initial_council_state(
    *,
    task_id: str,
    request_text: str,
    route: dict[str, Any],
    agent_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": task_id,
        "request_text": request_text,
        "chair": route["chair"],
        "order": agent_ids,
        "handoff": {
            "from": "",
            "to": agent_ids[0] if agent_ids else "",
            "task": "",
            "status": "queued",
        },
        "win_condition": "",
        "minimum_viable_context": [],
        "momentum_vector": "",
        "asymmetric_leverage": "",
        "leverage_patch": "",
        "execution_guidance": "",
        "invariants": [],
        "invariant_check": {
            "status": "pending",
            "notes": [],
        },
        "hard_halt": False,
        "decision": {
            "verdict": "pending",
            "summary": "",
            "next_action": "",
            "owner": route["chair"],
        },
        "turns": [],
    }


def state_context_text(state: dict[str, Any], *, max_chars: int) -> str:
    raw = json.dumps(state, indent=2, sort_keys=False)
    if len(raw) <= max_chars:
        return raw
    return raw[-max_chars:]


def parse_structured_turn(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("council turn must be a JSON object")
    return normalize_turn_payload(payload)


def normalize_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    state_patch = payload.get("state_patch") if isinstance(payload.get("state_patch"), dict) else {}
    invariant_check = state_patch.get("invariant_check") if isinstance(state_patch.get("invariant_check"), dict) else {}
    decision = state_patch.get("decision") if isinstance(state_patch.get("decision"), dict) else {}
    status = str(invariant_check.get("status") or "pending").strip().lower()
    if status not in INVARIANT_STATUS_ORDER:
        status = "pending"
    verdict = str(decision.get("verdict") or "pending").strip().lower()
    if verdict not in DECISION_VERDICTS:
        verdict = "pending"
    return {
        "position": str(payload.get("position") or "").strip(),
        "key_point": str(payload.get("key_point") or "").strip(),
        "risk": str(payload.get("risk") or "").strip(),
        "next_move": str(payload.get("next_move") or "").strip(),
        "confidence": _normalize_confidence(payload.get("confidence")),
        "state_patch": {
            "win_condition": str(state_patch.get("win_condition") or "").strip(),
            "minimum_viable_context": _normalize_context_list(state_patch.get("minimum_viable_context")),
            "momentum_vector": str(state_patch.get("momentum_vector") or "").strip(),
            "asymmetric_leverage": str(state_patch.get("asymmetric_leverage") or "").strip(),
            "leverage_patch": str(state_patch.get("leverage_patch") or "").strip(),
            "execution_guidance": str(state_patch.get("execution_guidance") or "").strip(),
            "invariants": _normalize_string_list(state_patch.get("invariants")),
            "invariant_check": {
                "status": status,
                "notes": _normalize_string_list(invariant_check.get("notes")),
            },
            "hard_halt": bool(state_patch.get("hard_halt")),
            "decision": {
                "verdict": verdict,
                "summary": str(decision.get("summary") or "").strip(),
                "next_action": str(decision.get("next_action") or "").strip(),
            },
        },
    }


def apply_turn_patch(state: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(state))
    patch = turn["structured"]["state_patch"]
    for key in (
        "win_condition",
        "momentum_vector",
        "asymmetric_leverage",
        "leverage_patch",
        "execution_guidance",
    ):
        value = patch.get(key)
        if isinstance(value, str) and value:
            merged[key] = value
    merged["minimum_viable_context"] = _merge_context(
        merged.get("minimum_viable_context"),
        patch.get("minimum_viable_context"),
    )
    merged["invariants"] = _merge_unique(
        merged.get("invariants"),
        patch.get("invariants"),
    )
    current_check = merged.get("invariant_check", {"status": "pending", "notes": []})
    incoming_check = patch.get("invariant_check", {"status": "pending", "notes": []})
    if INVARIANT_STATUS_ORDER[incoming_check["status"]] > INVARIANT_STATUS_ORDER[current_check["status"]]:
        current_check["status"] = incoming_check["status"]
    current_check["notes"] = _merge_unique(current_check.get("notes"), incoming_check.get("notes"))
    merged["invariant_check"] = current_check
    merged["hard_halt"] = bool(merged.get("hard_halt")) or bool(patch.get("hard_halt"))
    decision = merged.get("decision", {"verdict": "pending", "summary": "", "next_action": "", "owner": merged.get("chair", "bubba")})
    incoming_decision = patch.get("decision", {})
    for key in ("summary", "next_action"):
        value = incoming_decision.get(key)
        if isinstance(value, str) and value:
            decision[key] = value
    if incoming_decision.get("verdict") in DECISION_VERDICTS and incoming_decision["verdict"] != "pending":
        decision["verdict"] = incoming_decision["verdict"]
    if merged["hard_halt"] and decision.get("verdict") == "pending":
        decision["verdict"] = "halt"
    merged["decision"] = decision
    order = merged.get("order", [])
    next_agent = ""
    if isinstance(order, list):
        try:
            next_index = order.index(turn["agent"]) + 1
            if next_index < len(order):
                next_agent = str(order[next_index])
        except ValueError:
            next_agent = ""
    merged["handoff"] = {
        "from": turn["agent"],
        "to": next_agent,
        "task": turn["structured"].get("next_move", ""),
        "status": "complete" if not next_agent else "ready",
    }
    merged_turns = list(merged.get("turns", []))
    merged_turns.append(
        {
            "agent": turn["agent"],
            "name": turn["name"],
            "provider": turn["provider"],
            "model": turn["model"],
            "duration_ms": turn["duration_ms"],
            **turn["structured"],
        }
    )
    merged["turns"] = merged_turns
    return merged


def render_turn_markdown(turn: dict[str, Any]) -> str:
    structured = turn["structured"]
    state_patch = structured["state_patch"]
    decision = state_patch["decision"]
    invariant_check = state_patch["invariant_check"]
    lines = [
        f"1. Position: {structured['position'] or '(not provided)'}",
        f"2. Key point: {structured['key_point'] or '(not provided)'}",
        f"3. Risk: {structured['risk'] or '(not provided)'}",
        f"4. Next move: {structured['next_move'] or '(not provided)'}",
        f"5. Confidence: {structured['confidence']}%",
        "",
        "Structured Patch",
        f"- Win condition: {state_patch['win_condition'] or '(unchanged)'}",
        f"- MVC: {_format_context_list(state_patch['minimum_viable_context'])}",
        f"- Momentum vector: {state_patch['momentum_vector'] or '(unchanged)'}",
        f"- Asymmetric leverage: {state_patch['asymmetric_leverage'] or '(unchanged)'}",
        f"- Leverage patch: {state_patch['leverage_patch'] or '(unchanged)'}",
        f"- Execution guidance: {state_patch['execution_guidance'] or '(unchanged)'}",
        f"- Invariants: {', '.join(state_patch['invariants']) if state_patch['invariants'] else '(unchanged)'}",
        f"- Invariant check: {invariant_check['status']}",
        f"- Invariant notes: {', '.join(invariant_check['notes']) if invariant_check['notes'] else '(none)'}",
        f"- Hard halt: {'yes' if state_patch['hard_halt'] else 'no'}",
        f"- Decision verdict: {decision['verdict']}",
        f"- Decision summary: {decision['summary'] or '(unchanged)'}",
        f"- Decision next action: {decision['next_action'] or '(unchanged)'}",
    ]
    return "\n".join(lines)


def render_synthesis_markdown(state: dict[str, Any]) -> str:
    decision = state.get("decision", {})
    invariant_check = state.get("invariant_check", {})
    lines = [
        "# Steward Synthesis",
        "",
        f"- Verdict: `{decision.get('verdict', 'pending')}`",
        f"- Handoff: `{handoff_summary(state.get('handoff'))}`",
        f"- Win condition: {state.get('win_condition') or '(not set)'}",
        f"- Leverage patch: {state.get('leverage_patch') or '(not set)'}",
        f"- Invariant check: `{invariant_check.get('status', 'pending')}`",
        f"- Decision summary: {decision.get('summary') or '(not set)'}",
        f"- Next action: {decision.get('next_action') or '(not set)'}",
        "",
    ]
    return "\n".join(lines)


def handoff_summary(handoff: Any) -> str:
    if not isinstance(handoff, dict):
        return "none"
    source = str(handoff.get("from") or "").strip() or "steward"
    target = str(handoff.get("to") or "").strip() or "complete"
    task = str(handoff.get("task") or "").strip()
    status = str(handoff.get("status") or "").strip() or "unknown"
    if task:
        return f"{source} -> {target} ({status}) :: {task}"
    return f"{source} -> {target} ({status})"


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _normalize_context_list(value: Any) -> list[dict[str, Any] | str]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any] | str] = []
    seen: set[str] = set()
    for item in value:
        normalized: dict[str, Any] | str | None = None
        if isinstance(item, dict):
            field = str(item.get("field") or "").strip()
            if not field:
                continue
            normalized = {"field": field}
            for key in ("type", "description"):
                text = str(item.get(key) or "").strip()
                if text:
                    normalized[key] = text
        else:
            text = str(item or "").strip()
            if not text:
                continue
            normalized = text
        encoded = json.dumps(normalized, sort_keys=True)
        if encoded in seen:
            continue
        seen.add(encoded)
        items.append(normalized)
    return items


def _normalize_confidence(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, normalized))


def _merge_unique(current: Any, incoming: Any) -> list[str]:
    merged = _normalize_string_list(current)
    for item in _normalize_string_list(incoming):
        if item not in merged:
            merged.append(item)
    return merged


def _merge_context(current: Any, incoming: Any) -> list[dict[str, Any] | str]:
    merged = _normalize_context_list(current)
    seen = {json.dumps(item, sort_keys=True) for item in merged}
    for item in _normalize_context_list(incoming):
        encoded = json.dumps(item, sort_keys=True)
        if encoded in seen:
            continue
        seen.add(encoded)
        merged.append(item)
    return merged


def _format_context_list(items: list[dict[str, Any] | str]) -> str:
    if not items:
        return "(unchanged)"
    rendered: list[str] = []
    for item in items:
        if isinstance(item, dict):
            label = item.get("field", "field")
            detail = item.get("type") or item.get("description") or ""
            rendered.append(f"{label} ({detail})" if detail else label)
        else:
            rendered.append(str(item))
    return ", ".join(rendered)
