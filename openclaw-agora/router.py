from __future__ import annotations

from typing import Any

from .council import (
    CHAIR_ID,
    EXECUTION_ID,
    INNOVATION_ID,
    MOMENTUM_ID,
    RISK_ID,
    council_agent_ids,
    unique_order,
)

ARCHITECTURE_KEYWORDS = {
    "architecture",
    "design",
    "router",
    "orchestrate",
    "orchestrator",
    "workflow",
    "spec",
    "system",
    "protocol",
    "governance",
    "plan",
    "strategy",
}

IMPLEMENTATION_KEYWORDS = {
    "build",
    "implement",
    "fix",
    "patch",
    "code",
    "script",
    "run",
    "debug",
    "test",
    "deploy",
    "refactor",
    "automation",
    "execute",
}

HEAVY_WORKLOAD_KEYWORDS = {
    "docker",
    "scrape",
    "browser",
    "playwright",
    "media",
    "batch",
    "monitor",
    "transcode",
    "crawl",
    "long-running",
    "remote",
    "dellmac",
    "cluster",
}

HIGH_RISK_KEYWORDS = {
    "delete",
    "destroy",
    "production",
    "deploy",
    "publish",
    "rotate",
    "secret",
    "password",
    "migrate",
    "drop",
    "reset",
    "webhook",
    "public",
    "expose",
}

MEDIUM_RISK_KEYWORDS = {
    "telegram",
    "gateway",
    "auth",
    "allowlist",
    "config",
    "network",
    "worker",
    "ssh",
}


def _score(text: str, keywords: set[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def decide_route(
    request_text: str,
    *,
    risk_override: str | None = None,
    worker_override: str | None = None,
) -> dict[str, Any]:
    text = request_text.lower()
    architecture_score = _score(text, ARCHITECTURE_KEYWORDS)
    implementation_score = _score(text, IMPLEMENTATION_KEYWORDS)
    heavy_score = _score(text, HEAVY_WORKLOAD_KEYWORDS)
    high_risk_score = _score(text, HIGH_RISK_KEYWORDS)
    medium_risk_score = _score(text, MEDIUM_RISK_KEYWORDS)

    reasons: list[str] = []
    if architecture_score:
        reasons.append(f"architecture_score={architecture_score}")
    if implementation_score:
        reasons.append(f"implementation_score={implementation_score}")
    if heavy_score:
        reasons.append(f"heavy_score={heavy_score}")
    if high_risk_score:
        reasons.append(f"high_risk_score={high_risk_score}")
    if medium_risk_score:
        reasons.append(f"medium_risk_score={medium_risk_score}")

    planning_lead = INNOVATION_ID if architecture_score >= implementation_score else EXECUTION_ID
    review_lead = RISK_ID
    synthesis_lead = CHAIR_ID
    council_order = unique_order(
        planning_lead,
        MOMENTUM_ID,
        INNOVATION_ID,
        EXECUTION_ID,
        review_lead,
        synthesis_lead,
    )

    risk_level = "low"
    if high_risk_score:
        risk_level = "high"
    elif implementation_score or architecture_score or medium_risk_score:
        risk_level = "medium"

    if risk_override:
        risk_level = risk_override
        reasons.append(f"risk_override={risk_override}")

    approval_required = risk_level == "high"

    assigned_worker = "forge-dellmac" if heavy_score else "forge-m2"
    if worker_override:
        assigned_worker = worker_override
        reasons.append(f"worker_override={worker_override}")

    if risk_level == "high":
        mode = "council-debate"
        verification = "full council debate plus forge verification"
    elif implementation_score or heavy_score:
        mode = "council-execution"
        verification = "forge execution with full council review"
    else:
        mode = "council"
        verification = "full council review"

    if heavy_score:
        reasons.append("remote-heavy workload routed to forge-dellmac")
    if planning_lead == INNOVATION_ID:
        reasons.append("b2b2 leads when novelty, architecture, or strategy dominate")
    else:
        reasons.append("myboy leads when implementation, timing, or execution dominate")
    reasons.append("karen is always the primary risk review pass")
    reasons.append("bubba owns final synthesis and decision framing")

    return {
        "mode": mode,
        "chair": CHAIR_ID,
        "planning_lead": planning_lead,
        "innovation_lead": INNOVATION_ID,
        "execution_lead": EXECUTION_ID,
        "momentum_lead": MOMENTUM_ID,
        "review_lead": review_lead,
        "synthesis_lead": synthesis_lead,
        "council_order": council_order,
        "first_turn": planning_lead,
        "second_turn": review_lead,
        "verification": verification,
        "risk_level": risk_level,
        "approval_required": approval_required,
        "assigned_agents": council_agent_ids(),
        "assigned_workers": [assigned_worker],
        "reasons": reasons,
    }
