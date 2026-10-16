# Route: project work

Use for implementation, repair, or release work in a codebase or existing app.

1. Identify the real checkout, branch, dirty state, and serving process before editing. A named workspace may only be a shell or output directory.
2. Read only the repo's entry instructions, relevant route/source files, and directly required dependencies. Preserve existing work.
3. Follow its local `AGENTS.md`, skills, build/deploy procedure, and runtime conventions. This route is only a starting point.
4. Make the smallest coherent change. Do not scan unrelated projects or dump broad file listings into context.
5. Verify the requested outcome at the appropriate level. Do not claim runtime behavior from a passing unit test or HTTP status alone.

## Useful locations

- Main repositories: `~/Projects/` and selected apps under `~/Documents/`.
- Active projects: `~/Projects/Active/` (check each repo's current state).
- App/media project with known port-7700 runtime: Mike Media's real checkout may be outside the requested workspace; inspect live process evidence before editing.
- Saved specialist instructions: `~/.agents/skills/` and `~/.codex/skills/`.

Run `agentdesk find <project-name>` to locate a likely folder. Then inspect that project directly.
