# Agora

Agora is the implementation root for the file-driven multi-agent control plane running on `m2mac`.

## Intended Modules

- `steward/`: routing, approvals, state machine, synthesis
- `adapters/`: Codex and Antigravity bridges
- `forge/`: local and remote execution workers
- `policies/`: approval, routing, and memory rules
- `templates/`: task, brief, and artifact templates

## First Build Target

Implement a file-driven v1 on `m2mac` that:

1. creates a task directory
2. writes `brief.md` and `state.json`
3. routes a turn to one adapter
4. records outputs in task artifacts
5. returns one synthesized answer through Telegram

## Runtime State

The runtime Ledger should live under:

`~/.openclaw/agora/`

Keep repo code here and volatile state there.

## CLI

Run Agora from the workspace root:

```bash
python3 -m agora init
python3 -m agora brief "Build a Telegram router"
python3 -m agora cast
python3 -m agora convene <task-id>
python3 -m agora plan <task-id>
python3 -m agora review <task-id>
python3 -m agora run <task-id> --cmd "pytest -q"
python3 -m agora ship <task-id> --summary "Verified and ready."
python3 -m agora status <task-id> --json
python3 -m agora workers-status --json
python3 -m agora doctor --json
python3 -m agora transport-status --json
python3 -m agora transport-funnel --port 8787
python3 -m agora transport-webhook --url auto
python3 -m agora transport-polling
```

Core verbs:

- `brief`: create task, route, and scaffold artifacts
- `cast`: show the named council roster
- `convene`: run a live council pass through the named OpenClaw agents and write a transcript
- `plan`: assign the planning turn
- `review`: assign the challenge/review turn
- `run`: execute a local or remote Forge command
- `ship`: write the final synthesized artifact
- `logs`: inspect event and command history
- `artifacts`: list generated run artifacts
- `workers-status`: probe `forge-m2` and `forge-dellmac`
- `doctor`: inspect transport, Telegram webhook state, and worker readiness together
- `transport-status`: inspect Telegram polling/webhook state plus Tailscale readiness
- `transport-funnel`: attempt Tailscale Funnel on the local listener port
- `transport-webhook`: stage Telegram webhook mode using a public HTTPS URL or `auto` via Tailscale
- `transport-polling`: remove webhook config and fall back to long polling

Remote execution:

- local worker: `forge-m2`
- remote worker: `forge-dellmac` via `ssh dellmac`
- remote shell fallback: Agora probes `zsh`, then `bash`, then `sh` before executing on `dellmac`

Named council:

- `bubba`: chair and boss
- `b2b2`: innovation lead
- `myboy`: execution lead
- `potna`: momentum lead
- `karen`: risk lead
- Council workspaces were trimmed so council prompt bootstrap stays small.
- Council agents now run on direct Gemini Flash through the `google` provider and keep Ollama as a fallback.
- `convene` now fails loudly if a council turn falls off its primary provider or returns no text.
- `convene` now writes a structured council artifact at `council/state.json` and a synthesized decision at `council/synthesis.md`.
- `convene` now writes per-seat checkpoints into `council/checkpoints/` and updates an explicit `handoff` object in the shared state.

## Telegram Bridge

OpenClaw now loads a local plugin at:

`~/.openclaw/workspace/.openclaw/extensions/agora-control/`

That plugin registers `/agora` as an authenticated slash command and forwards subcommands into the local Agora CLI.

Examples:

```text
/agora brief Build a safer Telegram router
/agora cast
/agora convene <task-id>
/agora state <task-id>
/agora status <task-id>
/agora plan <task-id>
/agora review <task-id>
/agora run <task-id> worker=forge-dellmac :: pytest -q
/agora ship <task-id> Ready for review.
/agora workers
/agora doctor
/agora transport
/agora transport funnel
/agora transport webhook auto
/agora transport polling
```

Local visual viewer:

```bash
python3 -m agora watch <task-id> --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765/?task=<task-id>`.

The plugin is configured in:

`~/.openclaw/openclaw.json`

## Transport Notes

Agora now exposes transport inspection, webhook verification, and worker health commands.

Current deployed state on `m2mac`:

1. `tailscale-app` is installed and signed in on macOS
2. Funnel publishes `https://m2mac.tailnet-example.ts.net/` to the local OpenClaw webhook listener on `127.0.0.1:8787`
3. OpenClaw Telegram is running in webhook mode at `https://m2mac.tailnet-example.ts.net/telegram-webhook`
4. `python3 -m agora doctor --json` verifies the live Telegram webhook and both Forge workers
5. `python3 -m agora cast`, `python3 -m agora convene <task-id>`, and `python3 -m agora state <task-id>` expose the named council and its structured handoff ledger

If webhook mode ever needs to be rolled back quickly, use `python3 -m agora transport-polling` and restart the OpenClaw gateway.

## Gemini Notes

- The council fast path now uses `google/gemini-2.5-flash`.
- The Gemini API key is loaded from the OpenClaw runtime environment, so the council no longer depends on `google-antigravity` / Code Assist auth.
- The structured handoff contract now lives in `council/state.json` so Telegram can return Bubba's verdict without scraping prose.

## OSS Patterns

- The strongest external patterns adopted so far are checkpointed state and explicit handoffs.
- See `agora/OSS_PATTERNS.md` for the short list of systems worth stealing from.

## Viewer

- `watch` serves a local live dashboard for seats, handoffs, checkpoints, events, and the shared council state.
- The viewer polls the task ledger every 2 seconds and now reflects state updates after each completed seat, not just after final synthesis.
