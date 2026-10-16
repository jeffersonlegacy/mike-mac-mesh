# Route: Mac and files

Use for locating files, understanding folder layout, or planning organization.

1. Start with `agentdesk map` for the known user-facing roots; use `agentdesk find <filename words>` for scoped filename lookup.
2. For a specific synced or removable location, open the exact Finder folder and inspect its current state. Cloud placeholders and external volumes can be absent from ordinary local search.
3. Check symlinks, mounted volumes, open processes, and file ownership before changing paths used by an app or service.
4. Prefer an index, alias, or documented route over moving existing files. Never bulk-rename, move, or delete without previewing the exact affected paths.
5. Keep private app data (`~/Library`, browser profiles, credentials, and agent databases) outside broad scans.

## Current organization anchors

- Projects and source: `~/Projects/`
- Personal, business, work, and archived documents: `~/Documents/`
- Desktop captures and incoming media: `~/Desktop/`
- Media library: `~/Media/` (includes HP scan workflows)
- Agent instructions and skills: `~/.codex/`, `~/.agents/`, `~/.claude/`, `~/.gemini/`, `~/.openclaw/`
- Offloaded Mac data may be on mounted APFS volumes; check `mount` and Finder before concluding an item is unavailable.
