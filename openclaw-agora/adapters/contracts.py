from __future__ import annotations

from pathlib import Path
from typing import Any

from ..council import COUNCIL_MEMBERS, council_member


def _load_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_brief(
    template_path: Path,
    *,
    request_text: str,
    route: dict[str, Any],
    approval_required: bool,
) -> str:
    template = _load_template(template_path)
    replacements = {
        "<original user request>": request_text,
        "<what success looks like>": f"Produce a verified outcome for: {request_text}",
        "<constraint>": "Keep task state explicit and artifacts inspectable.",
        "<fact>": f"Bubba chairs the council and {route['planning_lead']} leads the first pass.",
        "<unknown>": "Council output has not been written yet.",
        "<chair>": route["chair"],
        "<planning lead>": route["planning_lead"],
        "<innovation lead>": route["innovation_lead"],
        "<execution lead>": route["execution_lead"],
        "<momentum lead>": route["momentum_lead"],
        "<review lead>": route["review_lead"],
        "<council order>": " -> ".join(route["council_order"]),
        "<method>": route["verification"],
        "<gate or none>": "Human approval required before risky execution."
        if approval_required
        else "none",
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template


def render_agent_assignment(
    *,
    agent: str,
    assignment_type: str,
    task_id: str,
    request_text: str,
    route: dict[str, Any],
    state: dict[str, Any],
) -> str:
    member = council_member(agent)
    title = f"{member.name} {assignment_type.title()} Assignment"
    return f"""# {title}

Task ID: `{task_id}`
Status: pending
Assigned by: Steward

## Identity

- Name: `{member.name}`
- Council title: `{member.title}`
- Mandate: {member.mandate}
- Style: {member.style}

## Request

{request_text}

## Current Task State

- Status: `{state["status"]}`
- Risk: `{state["risk_level"]}`
- Priority: `{state["priority"]}`
- Chair: `{route["chair"]}`
- Planning lead: `{route["planning_lead"]}`
- Innovation lead: `{route["innovation_lead"]}`
- Execution lead: `{route["execution_lead"]}`
- Momentum lead: `{route["momentum_lead"]}`
- Review lead: `{route["review_lead"]}`
- Council order: `{" -> ".join(route["council_order"])}` 
- Verification: `{route["verification"]}`

## Deliverable

- Summary
- Position for this role
- Assumptions
- Risks
- Next action
- Confidence

## Notes

Read the other council notes before finalizing if they already exist. Write your output below this line.
"""


def render_plan_file(task_id: str, request_text: str, route: dict[str, Any]) -> str:
    roster = "\n".join(
        f"- `{member.id}`: {member.name} ({member.title})"
        for member in COUNCIL_MEMBERS
    )
    return f"""# Execution Plan

Task ID: `{task_id}`

## Request

{request_text}

## Route

- Chair: `{route["chair"]}`
- Planning lead: `{route["planning_lead"]}`
- Review lead: `{route["review_lead"]}`
- Council order: `{" -> ".join(route["council_order"])}` 
- Verification: `{route["verification"]}`
- Worker: `{route["assigned_workers"][0]}`

## Council

{roster}

## Plan

- Pending council plan

## Execution Notes

- Add commands here before running `python3 -m agora run ...`.
"""


def render_result(
    *,
    task_id: str,
    state: dict[str, Any],
    route: dict[str, Any],
    approvals: dict[str, Any],
    command_rows: list[dict[str, Any]],
    summary: str | None,
) -> str:
    last_run = command_rows[-1] if command_rows else None
    run_section = "- No forge run recorded yet."
    if last_run:
        run_section = "\n".join(
            [
                f"- Worker: `{last_run['worker']}`",
                f"- Exit code: `{last_run['returncode']}`",
                f"- Command: `{last_run['command']}`",
                f"- Started: `{last_run['started_at']}`",
                f"- Finished: `{last_run['finished_at']}`",
            ]
        )

    summary_line = summary or "Steward synthesis generated from current task artifacts."
    return f"""# Result

Task ID: `{task_id}`

## Summary

{summary_line}

## Current State

- Status: `{state["status"]}`
- Risk: `{state["risk_level"]}`
- Approval required: `{approvals["required"]}`
- Approved: `{approvals["approved"]}`

## Route

- Mode: `{route["mode"]}`
- Chair: `{route["chair"]}`
- Planning lead: `{route["planning_lead"]}`
- Review lead: `{route["review_lead"]}`
- Council order: `{" -> ".join(route["council_order"])}` 
- Verification: `{route["verification"]}`

## Latest Run

{run_section}

## Next Action

- Review council artifacts and promote any durable notes into stable memory docs only after approval.
"""
