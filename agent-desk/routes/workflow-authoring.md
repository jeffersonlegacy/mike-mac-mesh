# Route: workflow authoring

Use when a task should become a reusable agent capability.

1. Put a human-readable `SKILL.md` or playbook at the route's entrance. It states when to use it, scope, steps, safety boundaries, and exact inputs/outputs.
2. Put deterministic, repeatable operations in adjacent `scripts/`; keep decision-making and exceptions in markdown.
3. Make scripts discoverable from the playbook, runnable with standard local tools, and safe by default. Provide `--help`; use preview/dry-run for data changes.
4. Keep evidence and examples in `references/` and templates in `templates/`; load them only when the workflow requires them.
5. Register the route in the relevant short index and agent ecosystem. Do not duplicate the full procedure into global instructions.
6. Validate script syntax and its no-op/help path. Never put credentials or secret values in a playbook, script, or output.

## Existing conventions

- Codex-style skills use a folder containing `SKILL.md`, optional `scripts/`, `references/`, and `assets/`.
- This Mac already has specialist skills under `~/.agents/skills/` and `~/.codex/skills/`. Inspect before adding a duplicate.
- For a repo-specific capability, keep it in that repository unless multiple workflows clearly need the same shared skill.
