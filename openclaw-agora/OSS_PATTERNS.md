# OSS Patterns For Agora

Agora should borrow from the best open-source agent systems without inheriting their bloat.

## Best Patterns

- `LangGraph`
  - Best idea: explicit shared state plus checkpointing at each step.
  - Repo: [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)
  - Agora fit: every council seat should leave a machine-readable state artifact, not just a transcript.

- `OpenAI Swarm`
  - Best idea: handoffs are first-class, lightweight, and easy to inspect.
  - Repo: [openai/swarm](https://github.com/openai/swarm)
  - Agora fit: the council state should always expose who just spoke, who is next, and what task is being handed off.

- `Microsoft AutoGen`
  - Best idea: controlled multi-agent conversation with constrained speaker transitions.
  - Repo: [microsoft/autogen](https://github.com/microsoft/autogen)
  - Agora fit: do not let agents free-chat. Keep explicit order, legal transitions, and termination conditions.

- `CrewAI`
  - Best idea: separate autonomous collaboration from deterministic flow execution.
  - Repo: [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)
  - Agora fit: council for reasoning, Steward/Forge for deterministic execution.

- `OpenHands`
  - Best idea: environments, artifacts, and evaluation matter more than persona theatrics.
  - Repo: [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands)
  - Agora fit: council output should be judged by real artifacts, commands, and verification, not by how convincing it sounds.

## Adopted In Agora

- Structured council ledger in `council/state.json`
- Explicit `handoff` state in the council artifact
- Per-turn checkpoints in `council/checkpoints/`
- Fixed council order with Bubba as final chair
- Direct Gemini Flash path for the council fast lane

## Next Candidates

- Add an evaluator pass after Bubba so the final verdict is scored against a checklist before shipping.
- Add interrupt gates for high-risk tasks so Steward can require human approval before execution.
- Add resumable replay from the latest checkpoint instead of rerunning the full council after a failure.
- Add route policies that switch between `council`, `council-execution`, and `single-seat` based on task shape.
