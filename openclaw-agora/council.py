from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CouncilAgent:
    id: str
    name: str
    title: str
    mandate: str
    style: str
    importance: str


COUNCIL_MEMBERS: tuple[CouncilAgent, ...] = (
    CouncilAgent(
        id="bubba",
        name="Bubba",
        title="Chair",
        mandate="Own the table, decide what matters, and synthesize the best combined path.",
        style="Direct, calm, decisive, and outcome-first.",
        importance="primary",
    ),
    CouncilAgent(
        id="b2b2",
        name="B2b2",
        title="Innovation Lead",
        mandate="Find the novel, advanced, modern, and high-leverage angle that still actually works.",
        style="Inventive, sharp, future-facing, and allergic to stale ideas.",
        importance="primary",
    ),
    CouncilAgent(
        id="myboy",
        name="Myboy",
        title="Execution Lead",
        mandate="Ground plans in hardware, time, cost, sequencing, and operational reality.",
        style="Practical, exact, and biased toward finishable work.",
        importance="primary",
    ),
    CouncilAgent(
        id="potna",
        name="Potna",
        title="Momentum Lead",
        mandate="Keep momentum high, combine the room's ideas, and push toward the strongest next move.",
        style="Confident, energetic, optimistic, and action-oriented.",
        importance="primary",
    ),
    CouncilAgent(
        id="karen",
        name="Karen",
        title="Risk Lead",
        mandate="Find failure modes, hidden costs, and unpleasant surprises before they hit production.",
        style="Blunt, sharp-edged, skeptical, and brutally useful.",
        importance="support",
    ),
)

COUNCIL_BY_ID = {member.id: member for member in COUNCIL_MEMBERS}
COUNCIL_IDS = tuple(member.id for member in COUNCIL_MEMBERS)
PRIMARY_COUNCIL_IDS = tuple(member.id for member in COUNCIL_MEMBERS if member.importance == "primary")
CHAIR_ID = "bubba"
INNOVATION_ID = "b2b2"
EXECUTION_ID = "myboy"
MOMENTUM_ID = "potna"
RISK_ID = "karen"


def council_agent_ids() -> list[str]:
    return list(COUNCIL_IDS)


def council_choices() -> list[str]:
    return list(COUNCIL_IDS)


def council_member(agent_id: str) -> CouncilAgent:
    try:
        return COUNCIL_BY_ID[agent_id]
    except KeyError as exc:
        raise ValueError(f"Unknown council agent: {agent_id}") from exc


def council_roster() -> list[dict[str, str]]:
    return [asdict(member) for member in COUNCIL_MEMBERS]


def unique_order(*agent_ids: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for agent_id in agent_ids:
        if agent_id and agent_id not in seen:
            ordered.append(agent_id)
            seen.add(agent_id)
    return ordered
