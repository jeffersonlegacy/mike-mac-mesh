# Agent Desk

One Finder-visible index for agent-assisted work across this Mac. It adds a markdown-and-script layer alongside existing apps, repositories, skills, and production workflows; it does not move or replace them.

## Start

- In Finder, open this folder and choose a route under `routes/`.
- In Terminal, run `agentdesk route <topic>` to find the shortest relevant playbook.
- Run `agentdesk map` for the known home-folder layout, or `agentdesk find <word>` to locate matching filenames in selected work folders.

## Routes

| Need | Route |
|---|---|
| Identify the actual project/runtime and keep changes scoped | [Project work](routes/project-work.md) |
| Inspect, organize, or find files across the Mac | [Mac and files](routes/mac-and-files.md) |
| Save a repeatable workflow as markdown plus a script | [Workflow authoring](routes/workflow-authoring.md) |
| Keep agent context small and choose how much work to do | [Efficient agent work](routes/efficient-agent-work.md) |
| Produce or repair documents and media | [Documents and media](routes/documents-media.md) |

## Layout principles

1. Keep source files in their current home. Add navigation and routing before considering any moves.
2. Put a short `README.md` or agent instruction at a domain folder's entrance; link to detailed playbooks instead of copying them.
3. Put repeatable commands in `scripts/`, with a preview or dry-run before any operation that moves, overwrites, or deletes user data.
4. Keep active source, generated output, archives, and reference material distinct within each domain where practical.
5. Let each repository keep its own `AGENTS.md` and production procedure. This desk routes to them; it does not override them.

## This first pass

It maps the existing home folders without scanning private app data, inventories, or project contents. The router's filename search is limited to `Projects`, `Documents`, `Desktop`, `Downloads`, and `Media`; it skips hidden paths and caps results. Nothing has been moved or deleted.
