#!/usr/bin/env python3
"""Small, bounded router for the Finder-visible Agent Desk."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DESK = Path(__file__).resolve().parents[1]
HOME = Path.home()
ROUTES = {
    "project-work": ("repo, code, app, bug, runtime, deploy, project", "Identify the real checkout and follow its local instructions."),
    "mac-and-files": ("mac, finder, file, files, folder, folders, environment, organize, locate, search", "Use bounded lookup; preserve current paths and data."),
    "workflow-authoring": ("skill, workflow, markdown, script, reusable, agent", "Keep decisions in markdown and deterministic steps in scripts."),
    "efficient-agent-work": ("token, context, efficient, scope, plan, verify", "Load only the route and evidence needed for the outcome."),
    "documents-media": ("document, pdf, video, image, media, presentation, artifact", "Preserve originals and verify the rendered deliverable."),
}
SEARCH_ROOTS = [HOME / p for p in ("Projects", "Documents", "Desktop", "Downloads", "Media")]


def route(query: str, should_open: bool) -> int:
    words = set(query.lower().replace("-", " ").split())
    scores = []
    for key, (tags, _) in ROUTES.items():
        tagset = set(tags.replace(",", " ").split())
        scores.append((len(words & tagset), key))
    score, key = max(scores)
    if score == 0:
        print("No strong route match. Available routes:")
        return routes()
    path = DESK / "routes" / f"{key}.md"
    print(f"{key}: {ROUTES[key][1]}\n{path}")
    if should_open:
        subprocess.run(["open", str(path)], check=False)
    return 0


def routes() -> int:
    for key, (tags, description) in ROUTES.items():
        print(f"{key:24} {description}\n  {DESK / 'routes' / (key + '.md')}")
    return 0


def folder_map() -> int:
    roots = ["Projects", "Documents", "Desktop", "Downloads", "Media"]
    for name in roots:
        path = HOME / name
        if path.is_dir():
            children = sorted(p.name + "/" for p in path.iterdir() if p.is_dir() and not p.name.startswith("."))
            summary = ", ".join(children[:12]) + (f", … (+{len(children)-12})" if len(children) > 12 else "")
            print(f"{path}\n  {summary}")
    print("\nAgent configuration roots (contents intentionally not enumerated):")
    for name in (".codex", ".agents", ".claude", ".gemini", ".openclaw"):
        path = HOME / name
        if path.is_dir():
            print(f"  {path}")
    print(f"\nAgent index: {DESK / 'START HERE.md'}")
    return 0


def find_files(query: str) -> int:
    terms = query.lower().split()
    count = 0
    for root in SEARCH_ROOTS:
        if not root.is_dir():
            continue
        proc = subprocess.run(["rg", "--files", "--hidden", "-g", "!.**", "-g", "!node_modules", "-g", "!.git", "-g", "!dist", "-g", "!.next", str(root)], capture_output=True, text=True, timeout=20)
        for line in proc.stdout.splitlines():
            name = Path(line).name.lower()
            if all(term in name for term in terms):
                print(line)
                count += 1
                if count >= 40:
                    print("(stopped at 40 matches; narrow the search)")
                    return 0
    if count == 0:
        print("No filename matches in Projects, Documents, Desktop, Downloads, or Media.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Route work through the Agent Desk markdown playbooks.")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("start", help="Open the Agent Desk front door in Finder/editor")
    subs.add_parser("map", help="Show a shallow map of known user-facing roots")
    subs.add_parser("routes", help="List task routes")
    p_route = subs.add_parser("route", help="Choose a playbook from task keywords")
    p_route.add_argument("query", nargs="+", help="Task topic")
    p_route.add_argument("--open", action="store_true", help="Open the selected markdown route")
    p_find = subs.add_parser("find", help="Find filenames in selected work folders")
    p_find.add_argument("query", nargs="+", help="Words that must appear in the filename")
    args = parser.parse_args()
    if args.command == "start":
        subprocess.run(["open", str(DESK / "START HERE.md")], check=False)
        return 0
    if args.command == "map":
        return folder_map()
    if args.command == "routes":
        return routes()
    if args.command == "route":
        return route(" ".join(args.query), args.open)
    if args.command == "find":
        return find_files(" ".join(args.query))
    return 2


if __name__ == "__main__":
    sys.exit(main())
