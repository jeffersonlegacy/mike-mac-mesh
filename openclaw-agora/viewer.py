from __future__ import annotations

import html
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import AgoraPaths
from .ledger import load_jsonl, load_task, read_json


def recent_task_ids(paths: AgoraPaths, *, limit: int = 20) -> list[str]:
    if not paths.tasks_root.exists():
        return []
    tasks = [
        path for path in paths.tasks_root.iterdir() if path.is_dir() and path.name.startswith("agora-")
    ]
    tasks.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [path.name for path in tasks[:limit]]


def build_task_snapshot(paths: AgoraPaths, task_id: str) -> dict[str, Any]:
    task = load_task(paths, task_id)
    files = task["files"]
    council_state = read_json(files["council_state"]) if files["council_state"].exists() else {}
    checkpoints = []
    checkpoint_root = files.get("council_checkpoints")
    if checkpoint_root and Path(checkpoint_root).exists():
        for path in sorted(Path(checkpoint_root).glob("*.json")):
            payload = read_json(path)
            checkpoints.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "state": payload,
                    "handoff": payload.get("handoff", {}),
                    "decision": payload.get("decision", {}),
                    "invariant_check": payload.get("invariant_check", {}),
                }
            )
    return {
        "task_id": task_id,
        "state": task["state"],
        "route": task["route"],
        "approvals": task["approvals"],
        "council_state": council_state,
        "events": load_jsonl(files["events"]),
        "commands": load_jsonl(files["commands"]),
        "checkpoints": checkpoints,
        "task_root": str(files["root"]),
    }


def start_viewer(
    paths: AgoraPaths,
    *,
    task_id: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> dict[str, Any]:
    server = ThreadingHTTPServer((host, port), _make_handler(paths, task_id))
    url = f"http://{host}:{port}/"
    if task_id:
        url = f"{url}?task={task_id}"
    if open_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"url": url, "host": host, "port": port, "task_id": task_id}


def _make_handler(paths: AgoraPaths, default_task_id: str | None):
    class AgoraViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/tasks":
                self._send_json({"tasks": recent_task_ids(paths)})
                return
            if parsed.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if parsed.path == "/api/task":
                params = parse_qs(parsed.query)
                task_id = (params.get("task") or [default_task_id or ""])[0]
                if not task_id:
                    self._send_json({"error": "task_id required"}, status=400)
                    return
                try:
                    self._send_json(build_task_snapshot(paths, task_id))
                except FileNotFoundError:
                    self._send_json({"error": f"unknown task: {task_id}"}, status=404)
                return
            if parsed.path == "/api/stream":
                params = parse_qs(parsed.query)
                task_id = (params.get("task") or [default_task_id or ""])[0]
                if not task_id:
                    self._send_json({"error": "task_id required"}, status=400)
                    return
                self._send_sse(task_id)
                return
            if parsed.path == "/" or parsed.path == "/index.html":
                self._send_html(_render_shell(default_task_id))
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            data = json.dumps(payload, indent=2, sort_keys=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_html(self, payload: str, *, status: int = 200) -> None:
            data = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_sse(self, task_id: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            last_payload = ""
            try:
                while True:
                    try:
                        payload = build_task_snapshot(paths, task_id)
                    except FileNotFoundError:
                        self.wfile.write(b"event: error\ndata: {\"error\":\"unknown task\"}\n\n")
                        self.wfile.flush()
                        return
                    encoded = json.dumps(payload, sort_keys=False)
                    if encoded != last_payload:
                        frame = f"event: snapshot\ndata: {encoded}\n\n".encode("utf-8")
                        self.wfile.write(frame)
                        self.wfile.flush()
                        last_payload = encoded
                    else:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError):
                return

    return AgoraViewerHandler


def _render_shell(default_task_id: str | None) -> str:
    task_value = html.escape(default_task_id or "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agora Overworld</title>
  <style>
    :root {{
      --bg0: #061015;
      --bg1: #0b1b23;
      --bg2: #102733;
      --grass: #17342c;
      --path: #4b5a40;
      --water: #10384b;
      --panel: rgba(10, 20, 27, 0.84);
      --line: rgba(125, 191, 180, 0.18);
      --text: #edf6ef;
      --muted: #96b0a6;
      --bubba: #f6d365;
      --b2b2: #67d6ff;
      --myboy: #8cf0b5;
      --potna: #ff9f68;
      --karen: #ff6e7f;
      --ship: #8cf0b5;
      --review: #f6d365;
      --halt: #ff6e7f;
      --shadow: 0 18px 50px rgba(0,0,0,0.45);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "SF Mono", "IBM Plex Mono", Menlo, monospace;
      color: var(--text);
      background:
        radial-gradient(circle at 20% 10%, rgba(103,214,255,0.08), transparent 24%),
        radial-gradient(circle at 80% 0%, rgba(246,211,101,0.08), transparent 26%),
        linear-gradient(180deg, var(--bg0), var(--bg1) 40%, #07131a 100%);
      min-height: 100vh;
    }}
    .page {{
      width: min(1500px, calc(100vw - 24px));
      margin: 0 auto;
      padding: 14px 0 28px;
    }}
    .topbar > *,
    .layout > *,
    .card {{
      min-width: 0;
    }}
    .topbar {{
      display: grid;
      grid-template-columns: 1.1fr 1fr;
      gap: 14px;
      margin-bottom: 14px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--panel);
      backdrop-filter: blur(12px);
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 18px 20px;
      display: grid;
      gap: 14px;
      background:
        linear-gradient(135deg, rgba(18,48,39,0.88), rgba(7,17,24,0.9)),
        linear-gradient(45deg, transparent 0 49%, rgba(255,255,255,0.02) 50%, transparent 51%);
    }}
    .hero h1 {{
      margin: 0;
      font-size: clamp(24px, 3.4vw, 46px);
      letter-spacing: -0.05em;
    }}
    .hero-copy {{
      color: var(--muted);
      max-width: 60ch;
      line-height: 1.5;
    }}
    .pill-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      color: var(--muted);
      background: rgba(255,255,255,0.03);
      max-width: 100%;
      overflow-wrap: anywhere;
    }}
    .controls {{
      padding: 18px;
      display: grid;
      gap: 12px;
      align-content: start;
    }}
    .controls-grid {{
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
    }}
    input, select, button {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      color: var(--text);
      background: rgba(255,255,255,0.04);
    }}
    button {{
      cursor: pointer;
      background: linear-gradient(135deg, #183c47, #1f5f62);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 1.55fr 0.85fr;
      gap: 14px;
    }}
    .map-card {{
      padding: 14px;
    }}
    .map-shell {{
      position: relative;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      aspect-ratio: 1000 / 760;
      min-height: clamp(520px, 62vh, 820px);
      border-radius: 28px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.05);
      background:
        radial-gradient(circle at 18% 22%, rgba(30,95,82,0.62), transparent 18%),
        radial-gradient(circle at 74% 16%, rgba(16,56,75,0.6), transparent 16%),
        radial-gradient(circle at 82% 74%, rgba(30,95,82,0.42), transparent 14%),
        linear-gradient(180deg, #173127, #13271f 44%, #10231d 100%);
    }}
    .map-camera {{
      position: absolute;
      inset: 0;
      touch-action: none;
      transform-origin: center center;
      transition: transform 0.28s ease;
    }}
    .map-shell::before {{
      content: "";
      position: absolute;
      inset: 0;
      background-image:
        linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
      background-size: 42px 42px;
      pointer-events: none;
    }}
    .terrain {{
      position: absolute;
      inset: 0;
      pointer-events: none;
    }}
    .fog {{
      position: absolute;
      inset: 0;
      z-index: 4;
      pointer-events: none;
      background: radial-gradient(circle at 50% 50%, transparent 0%, rgba(0,0,0,0.42) 18%, rgba(0,0,0,0.72) 58%, rgba(0,0,0,0.86) 100%);
      transition: background 0.45s ease;
    }}
    .forest, .lake, .ruin {{
      position: absolute;
      border-radius: 999px;
      filter: blur(0.2px);
      opacity: 0.88;
    }}
    .forest {{
      background: radial-gradient(circle, rgba(27,75,54,0.7), rgba(18,49,35,0.15));
    }}
    .lake {{
      background: radial-gradient(circle, rgba(21,84,114,0.64), rgba(13,44,60,0.08));
    }}
    .ruin {{
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(80,93,70,0.28), rgba(40,49,37,0.12));
      border: 1px solid rgba(255,255,255,0.06);
    }}
    .track {{
      position: absolute;
      inset: 0;
      pointer-events: none;
    }}
    .path-line {{
      position: absolute;
      height: 6px;
      transform-origin: left center;
      border-radius: 999px;
      background:
        repeating-linear-gradient(
          90deg,
          rgba(237,246,239,0.08) 0 12px,
          rgba(237,246,239,0.24) 12px 24px,
          rgba(237,246,239,0.08) 24px 36px
        );
      background-size: 160px 100%;
      box-shadow: 0 0 14px rgba(255,255,255,0.12);
      animation: road-flow 6s linear infinite;
    }}
    .path-line.active {{
      background:
        repeating-linear-gradient(
          90deg,
          rgba(140,240,181,0.14) 0 12px,
          rgba(140,240,181,0.88) 12px 24px,
          rgba(140,240,181,0.18) 24px 36px
        );
      background-size: 140px 100%;
      box-shadow: 0 0 18px rgba(140,240,181,0.48);
    }}
    .traveler {{
      position: absolute;
      width: 18px;
      height: 18px;
      margin-left: -9px;
      margin-top: -9px;
      border-radius: 999px;
      background: radial-gradient(circle at 30% 30%, #fff, #8cf0b5 45%, rgba(140,240,181,0.1) 72%);
      box-shadow: 0 0 22px rgba(140,240,181,0.8);
      z-index: 8;
      transition: left 0.7s ease, top 0.7s ease, opacity 0.3s ease;
      animation: traveler-pulse 1.4s ease-in-out infinite;
    }}
    .landmark {{
      position: absolute;
      width: clamp(148px, 15vw, 176px);
      min-height: clamp(116px, 13vw, 136px);
      padding: clamp(12px, 1vw, 14px);
      border-radius: 20px;
      border: 1px solid rgba(255,255,255,0.08);
      background: linear-gradient(180deg, rgba(13,24,24,0.88), rgba(9,18,20,0.96));
      box-shadow: var(--shadow);
      z-index: 5;
      transition: transform 0.35s ease, box-shadow 0.35s ease, border-color 0.35s ease;
    }}
    .landmark.active {{
      transform: translateY(-6px) scale(1.02);
      border-color: rgba(140,240,181,0.9);
      box-shadow: 0 0 0 1px rgba(140,240,181,0.32), 0 16px 45px rgba(0,0,0,0.5);
    }}
    .landmark.focused {{
      outline: 2px solid rgba(246,211,101,0.7);
      outline-offset: 3px;
    }}
    .landmark.done {{
      border-color: rgba(103,214,255,0.42);
    }}
    .landmark .title {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 12px;
    }}
    .landmark .name {{
      font-size: clamp(16px, 1.2vw, 18px);
      letter-spacing: -0.03em;
      text-transform: none;
    }}
    .landmark .desc, .landmark .meta {{
      color: var(--muted);
      font-size: clamp(11px, 0.84vw, 12px);
      line-height: 1.45;
    }}
    .landmark .badge {{
      display: inline-flex;
      margin-top: 10px;
      border-radius: 999px;
      padding: 5px 9px;
      border: 1px solid rgba(255,255,255,0.1);
      font-size: 11px;
    }}
    .seat-myboy {{ box-shadow: inset 0 0 0 1px rgba(140,240,181,0.18), var(--shadow); }}
    .seat-potna {{ box-shadow: inset 0 0 0 1px rgba(255,159,104,0.18), var(--shadow); }}
    .seat-b2b2 {{ box-shadow: inset 0 0 0 1px rgba(103,214,255,0.18), var(--shadow); }}
    .seat-karen {{ box-shadow: inset 0 0 0 1px rgba(255,110,127,0.18), var(--shadow); }}
    .seat-bubba {{ box-shadow: inset 0 0 0 1px rgba(246,211,101,0.2), var(--shadow); }}
    .citadel {{
      position: absolute;
      left: 50%;
      top: 50%;
      width: clamp(240px, 24vw, 300px);
      min-height: clamp(172px, 18vw, 212px);
      transform: translate(-50%, -50%);
      z-index: 6;
      border-radius: 28px;
      border: 1px solid rgba(246,211,101,0.24);
      background:
        radial-gradient(circle at 50% 20%, rgba(246,211,101,0.12), transparent 50%),
        linear-gradient(180deg, rgba(28,25,18,0.95), rgba(14,18,17,0.96));
      box-shadow: 0 0 0 1px rgba(246,211,101,0.14), 0 22px 60px rgba(0,0,0,0.52);
      padding: clamp(16px, 1.4vw, 20px);
    }}
    .citadel h2 {{
      margin: 0 0 12px;
      font-size: clamp(22px, 1.8vw, 28px);
      letter-spacing: -0.04em;
    }}
    .citadel.focused {{
      box-shadow: 0 0 0 2px rgba(246,211,101,0.35), 0 22px 60px rgba(0,0,0,0.52);
    }}
    .citadel .mission {{
      font-size: 13px;
      line-height: 1.55;
      color: var(--muted);
      min-height: 60px;
    }}
    .citadel .verdict {{
      display: inline-flex;
      margin-top: 14px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.1);
    }}
    .legend {{
      position: absolute;
      left: 14px;
      bottom: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      z-index: 9;
    }}
    .legend .chip {{
      padding: 8px 10px;
      border-radius: 999px;
      background: rgba(7,15,16,0.78);
      border: 1px solid rgba(255,255,255,0.08);
      color: var(--muted);
      font-size: 11px;
    }}
    .landmark, .citadel {{
      cursor: pointer;
    }}
    .sidebar {{
      display: grid;
      gap: 14px;
    }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }}
    .panel-body {{
      padding: 16px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .stat {{
      border-radius: 16px;
      padding: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.03);
    }}
    .stat strong {{
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .stack {{
      display: grid;
      gap: 10px;
      max-height: 260px;
      overflow: auto;
      padding-right: 4px;
    }}
    .event, .checkpoint {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.03);
      border-radius: 16px;
      padding: 12px;
      overflow-wrap: anywhere;
    }}
    .checkpoint {{
      cursor: pointer;
      transition: border-color 0.2s ease, transform 0.2s ease;
    }}
    .checkpoint:hover {{
      border-color: rgba(246,211,101,0.45);
      transform: translateY(-1px);
    }}
    .checkpoint.active {{
      border-color: rgba(246,211,101,0.9);
      box-shadow: 0 0 0 1px rgba(246,211,101,0.3);
    }}
    .event time, .checkpoint code {{
      color: var(--muted);
      font-size: 11px;
    }}
    .event .payload {{
      max-height: 180px;
      overflow: auto;
      margin-top: 8px;
      padding-right: 4px;
    }}
    .focus-card {{
      display: grid;
      gap: 10px;
    }}
    .focus-name {{
      font-size: 22px;
      letter-spacing: -0.04em;
    }}
    .focus-meta {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .focus-block {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.03);
      border-radius: 14px;
      padding: 12px;
      overflow-wrap: anywhere;
    }}
    .focus-block strong {{
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: #dce7dc;
      line-height: 1.45;
      font-size: 12px;
    }}
    #json-state {{
      display: block;
      max-height: 360px;
      overflow: auto;
      padding-right: 4px;
    }}
    .mini-btn {{
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 11px;
      border: 1px solid var(--line);
      color: var(--muted);
      background: rgba(255,255,255,0.04);
    }}
    .muted {{ color: var(--muted); }}
    .ok {{ color: var(--ship); }}
    .warn {{ color: var(--review); }}
    .danger {{ color: var(--halt); }}
    .status-bubba {{ color: var(--bubba); }}
    .status-b2b2 {{ color: var(--b2b2); }}
    .status-myboy {{ color: var(--myboy); }}
    .status-potna {{ color: var(--potna); }}
    .status-karen {{ color: var(--karen); }}
    @keyframes road-flow {{
      from {{ background-position: 0 0; }}
      to {{ background-position: 160px 0; }}
    }}
    @keyframes traveler-pulse {{
      0%, 100% {{ transform: scale(1); box-shadow: 0 0 16px rgba(140,240,181,0.65); }}
      50% {{ transform: scale(1.25); box-shadow: 0 0 28px rgba(140,240,181,0.95); }}
    }}
    @media (max-width: 1100px) {{
      .topbar, .layout {{
        grid-template-columns: 1fr;
      }}
      .map-shell {{
        min-height: clamp(480px, 58vh, 760px);
      }}
      .controls-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 760px) {{
      .page {{
        width: calc(100vw - 12px);
      }}
      .map-shell {{
        min-height: 420px;
      }}
      .landmark {{
        width: min(42vw, 170px);
        min-height: 108px;
        padding: 11px;
      }}
      .citadel {{
        width: min(58vw, 272px);
      }}
      .hero-copy {{
        max-width: none;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="topbar">
      <section class="card hero">
        <div class="pill-row">
          <div class="pill">Agora Overworld</div>
          <div class="pill" id="refresh-status">Connecting stream...</div>
          <div class="pill" id="task-root">No task loaded</div>
        </div>
        <div>
          <h1>The Council Lands</h1>
          <div class="hero-copy">Watch Bubba, B2b2, Myboy, Potna, and Karen move the mission across the map. Paths light up, handoffs travel, and the citadel updates as the room converges.</div>
        </div>
      </section>
      <section class="card controls">
        <div class="controls-grid">
          <input id="task-input" placeholder="Task id" value="{task_value}">
          <select id="task-select"><option value="">Recent tasks</option></select>
          <button id="load-btn">Enter World</button>
        </div>
        <div class="pill-row">
          <div class="pill">Stream: SSE</div>
          <div class="pill">Mode: Overworld</div>
          <div class="pill" id="event-count">0 events</div>
          <div class="pill" id="replay-status">Live mode</div>
        </div>
      </section>
    </div>

    <div class="layout">
      <section class="card map-card">
        <div class="map-shell">
          <div class="map-camera" id="map-camera">
          <div class="terrain">
            <div class="forest" style="left:4%;top:6%;width:240px;height:220px"></div>
            <div class="forest" style="right:6%;top:10%;width:210px;height:180px"></div>
            <div class="forest" style="left:14%;bottom:12%;width:220px;height:180px"></div>
            <div class="lake" style="right:10%;bottom:14%;width:250px;height:180px"></div>
            <div class="ruin" style="left:40%;top:8%;width:150px;height:90px"></div>
            <div class="ruin" style="left:62%;top:58%;width:120px;height:84px"></div>
          </div>
          <div class="fog" id="fog"></div>
          <svg class="track" viewBox="0 0 1000 760" preserveAspectRatio="none">
            <line id="path-myboy-potna" class="path-line-svg" x1="180" y1="560" x2="330" y2="220" />
            <line id="path-potna-b2b2" class="path-line-svg" x1="330" y1="220" x2="780" y2="180" />
            <line id="path-b2b2-karen" class="path-line-svg" x1="780" y1="180" x2="790" y2="565" />
            <line id="path-karen-bubba" class="path-line-svg" x1="790" y1="565" x2="500" y2="380" />
            <line id="path-bubba-myboy" class="path-line-svg" x1="500" y1="380" x2="180" y2="560" />
          </svg>
          <div class="path-line" id="route-1"></div>
          <div class="path-line" id="route-2"></div>
          <div class="path-line" id="route-3"></div>
          <div class="path-line" id="route-4"></div>
          <div class="path-line" id="route-5"></div>
          <div class="traveler" id="traveler"></div>

          <article class="landmark seat-myboy" id="seat-myboy" style="left:9%;top:61%">
            <div class="title"><span class="status-myboy">Execution</span><span id="tone-myboy">waiting</span></div>
            <div class="name">Myboy</div>
            <div class="desc" id="desc-myboy">Grounded sequencing and feasibility.</div>
            <div class="meta" id="meta-myboy"></div>
          </article>

          <article class="landmark seat-potna" id="seat-potna" style="left:26%;top:16%">
            <div class="title"><span class="status-potna">Momentum</span><span id="tone-potna">waiting</span></div>
            <div class="name">Potna</div>
            <div class="desc" id="desc-potna">Carries the room forward.</div>
            <div class="meta" id="meta-potna"></div>
          </article>

          <article class="landmark seat-b2b2" id="seat-b2b2" style="right:8%;top:11%">
            <div class="title"><span class="status-b2b2">Innovation</span><span id="tone-b2b2">waiting</span></div>
            <div class="name">B2b2</div>
            <div class="desc" id="desc-b2b2">Novel leverage that actually works.</div>
            <div class="meta" id="meta-b2b2"></div>
          </article>

          <article class="landmark seat-karen" id="seat-karen" style="right:7%;bottom:11%">
            <div class="title"><span class="status-karen">Risk</span><span id="tone-karen">waiting</span></div>
            <div class="name">Karen</div>
            <div class="desc" id="desc-karen">Structural pressure and failure checks.</div>
            <div class="meta" id="meta-karen"></div>
          </article>

          <section class="citadel" id="citadel">
            <div class="pill-row">
              <div class="pill">Bubba</div>
              <div class="pill" id="verdict-badge">pending</div>
            </div>
            <h2>Citadel Of Synthesis</h2>
            <div class="mission" id="mission-text">Load a task to see the mission move across the world.</div>
            <div class="verdict" id="handoff-badge">steward -> waiting</div>
          </section>

          <div class="legend">
            <div class="chip" id="checkpoint-count">0 checkpoints</div>
            <div class="chip" id="turn-count">0 turns</div>
            <div class="chip" id="status-pill">status unknown</div>
          </div>
          </div>
          <div class="legend" style="right:14px; left:auto;">
            <button class="chip" id="zoom-out" type="button">-</button>
            <button class="chip" id="zoom-reset" type="button">reset</button>
            <button class="chip" id="zoom-in" type="button">+</button>
          </div>
        </div>
      </section>

      <aside class="sidebar">
        <section class="card">
          <div class="panel-head"><strong>Realm State</strong><span class="muted">live</span></div>
          <div class="panel-body">
            <div class="stats" id="stats"></div>
          </div>
        </section>

        <section class="card">
          <div class="panel-head"><strong>Focused District</strong><span class="muted" id="focus-seat-label">auto</span></div>
          <div class="panel-body">
            <div class="focus-card" id="focus-card"></div>
          </div>
        </section>

        <section class="card">
          <div class="panel-head"><strong>Checkpoint Trail</strong><span class="muted">council/checkpoints</span></div>
          <div class="panel-body">
            <div class="stack" id="checkpoints"></div>
          </div>
        </section>

        <section class="card">
          <div class="panel-head"><strong>Event Feed</strong><span class="muted">latest 30</span></div>
          <div class="panel-body">
            <div class="stack" id="timeline"></div>
          </div>
        </section>

        <section class="card">
          <div class="panel-head">
            <strong>Raw State</strong>
            <div style="display:flex;align-items:center;gap:8px">
              <span class="muted">shared ledger</span>
              <button id="state-toggle" class="mini-btn" type="button">expand</button>
            </div>
          </div>
          <div class="panel-body">
            <pre id="json-state">Select a task.</pre>
          </div>
        </section>
      </aside>
    </div>
  </div>
  <script>
    const seatOrder = ["myboy", "potna", "b2b2", "karen", "bubba"];
    const seatMeta = {{
      myboy: {{ label: "Execution", pos: [18, 56] }},
      potna: {{ label: "Momentum", pos: [33, 21] }},
      b2b2: {{ label: "Innovation", pos: [79, 18] }},
      karen: {{ label: "Risk", pos: [79, 57] }},
      bubba: {{ label: "Synthesis", pos: [50, 38] }},
    }};
    const routeSegments = [
      ["myboy", "potna"],
      ["potna", "b2b2"],
      ["b2b2", "karen"],
      ["karen", "bubba"],
      ["bubba", "myboy"],
    ];
    const taskInput = document.getElementById("task-input");
    const taskSelect = document.getElementById("task-select");
    const loadBtn = document.getElementById("load-btn");
    const mapCamera = document.getElementById("map-camera");
    const mapShell = document.querySelector(".map-shell");
    const refreshStatus = document.getElementById("refresh-status");
    const stateToggle = document.getElementById("state-toggle");
    let stream = null;
    let selectedSeat = "";
    let lastSnapshot = null;
    let replayCheckpoint = null;
    let zoomLevel = 1;
    let panX = 0;
    let panY = 0;
    let reconnectTimer = null;
    let reconnectDelayMs = 1000;
    let stateExpanded = false;
    let dragging = false;
    let pointerId = null;
    let startX = 0;
    let startY = 0;

    function qsTask() {{
      const params = new URLSearchParams(window.location.search);
      return params.get("task") || taskInput.value.trim();
    }}

    function setTask(taskId) {{
      const params = new URLSearchParams(window.location.search);
      if (taskId) params.set("task", taskId);
      else params.delete("task");
      history.replaceState(null, "", `${{window.location.pathname}}?${{params.toString()}}`);
      taskInput.value = taskId || "";
    }}

    function statusTone(status) {{
      if (["done", "ship", "pass"].includes(status)) return "ok";
      if (["blocked", "halt"].includes(status)) return "danger";
      if (["review", "reviewing"].includes(status)) return "warn";
      return "muted";
    }}

    function shortText(value, limit=120) {{
      if (!value) return "waiting";
      return value.length > limit ? `${{value.slice(0, limit - 1)}}…` : value;
    }}

    function escapeHtml(value) {{
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }}

    function shortJson(value, limit=900) {{
      const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
      return text.length > limit ? `${{text.slice(0, limit - 1)}}…` : text;
    }}

    function clearReconnect() {{
      if (reconnectTimer) {{
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }}
    }}

    function scheduleReconnect() {{
      if (reconnectTimer) return;
      refreshStatus.textContent = `Stream reconnecting in ${{Math.round(reconnectDelayMs / 1000)}}s`;
      reconnectTimer = setTimeout(async () => {{
        reconnectTimer = null;
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, 10000);
        await refresh();
        connectStream();
      }}, reconnectDelayMs);
    }}

    function applyStateView() {{
      const statePane = document.getElementById("json-state");
      statePane.style.maxHeight = stateExpanded ? "none" : "360px";
      stateToggle.textContent = stateExpanded ? "collapse" : "expand";
    }}

    function placeRouteLine(id, from, to, active) {{
      const el = document.getElementById(id);
      const [x1, y1] = seatMeta[from].pos;
      const [x2, y2] = seatMeta[to].pos;
      const dx = x2 - x1;
      const dy = y2 - y1;
      const length = Math.sqrt(dx * dx + dy * dy);
      const angle = Math.atan2(dy, dx) * 180 / Math.PI;
      el.style.left = `${{x1}}%`;
      el.style.top = `${{y1}}%`;
      el.style.width = `${{length}}%`;
      el.style.transform = `translateY(-50%) rotate(${{angle}}deg)`;
      el.classList.toggle("active", active);
      el.style.opacity = active ? "1" : "0.55";
    }}

    function renderStats(snapshot) {{
      const decision = snapshot.council_state?.decision || {{}};
      const invariant = snapshot.council_state?.invariant_check || {{}};
      const stats = [
        ["Quest", snapshot.state?.status || "unknown"],
        ["Verdict", decision.verdict || "pending"],
        ["Invariant", invariant.status || "pending"],
        ["Turns", String((snapshot.council_state?.turns || []).length)],
      ];
      document.getElementById("stats").innerHTML = stats.map(([label, value]) =>
        `<div class="stat"><strong>${{label}}</strong><div class="${{statusTone(String(value).toLowerCase())}}">${{value}}</div></div>`
      ).join("");
      document.getElementById("status-pill").textContent = `status ${{snapshot.state?.status || "unknown"}}`;
      document.getElementById("turn-count").textContent = `${{(snapshot.council_state?.turns || []).length}} turns`;
    }}

    function applyCamera() {{
      const bounds = mapShell?.getBoundingClientRect();
      const maxX = bounds ? Math.max(0, ((zoomLevel - 1) * bounds.width) / 2) : 0;
      const maxY = bounds ? Math.max(0, ((zoomLevel - 1) * bounds.height) / 2) : 0;
      panX = Math.max(-maxX, Math.min(maxX, panX));
      panY = Math.max(-maxY, Math.min(maxY, panY));
      mapCamera.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{zoomLevel}})`;
    }}

    function renderMap(snapshot) {{
      const turns = snapshot.council_state?.turns || [];
      const handoff = snapshot.council_state?.handoff || {{}};
      const completed = new Set(turns.map((turn) => turn.agent));
      const nextSeat = handoff.to || "";
      const activeSource = handoff.from || "";

      routeSegments.forEach(([from, to], index) => {{
        const active = (activeSource === from && nextSeat === to) || (!nextSeat && from === "bubba" && activeSource === "bubba");
        placeRouteLine(`route-${{index + 1}}`, from, to, active);
      }});

      seatOrder.forEach((seat) => {{
        const card = document.getElementById(`seat-${{seat}}`);
        const tone = document.getElementById(`tone-${{seat}}`);
        const desc = document.getElementById(`desc-${{seat}}`);
        const meta = document.getElementById(`meta-${{seat}}`);
        const turn = turns.find((item) => item.agent === seat);
        if (!card || !tone || !desc || !meta) return;
        card.classList.toggle("done", completed.has(seat));
        card.classList.toggle("active", nextSeat === seat || (!nextSeat && activeSource === seat));
        card.classList.toggle("focused", selectedSeat === seat);
        tone.textContent = turn ? `${{turn.confidence}}%` : (nextSeat === seat ? "up next" : "waiting");
        desc.textContent = shortText(turn?.key_point || turn?.next_move || desc.textContent, 150);
        meta.textContent = turn ? `${{turn.duration_ms || "?"}}ms · ${{turn.model || "model?"}}` : (nextSeat === seat ? "mission incoming" : "");
      }});

      const traveler = document.getElementById("traveler");
      const targetSeat = nextSeat || activeSource || "bubba";
      const [tx, ty] = seatMeta[targetSeat]?.pos || [50, 38];
      traveler.style.left = `${{tx}}%`;
      traveler.style.top = `${{ty}}%`;
      traveler.style.opacity = snapshot.council_state ? "1" : "0";

      const revealSeats = new Set([...completed, targetSeat, "bubba"]);
      const fog = document.getElementById("fog");
      const reveals = Array.from(revealSeats).map((seat) => {{
        const [x, y] = seatMeta[seat]?.pos || [50, 38];
        return `radial-gradient(circle at ${{x}}% ${{y}}%, rgba(0,0,0,0) 0 10%, rgba(0,0,0,0.12) 13%, rgba(0,0,0,0.68) 22%)`;
      }});
      fog.style.background = [...reveals, "linear-gradient(180deg, rgba(0,0,0,0.16), rgba(0,0,0,0.7))"].join(",");
    }}

    function renderCitadel(snapshot) {{
      const state = snapshot.council_state || {{}};
      const decision = state.decision || {{}};
      const handoff = state.handoff || {{}};
      const citadel = document.getElementById("citadel");
      citadel.classList.toggle("focused", selectedSeat === "bubba");
      document.getElementById("verdict-badge").textContent = decision.verdict || "pending";
      document.getElementById("mission-text").textContent = shortText(
        handoff.task || decision.summary || state.win_condition || "No mission yet.",
        360,
      );
      document.getElementById("handoff-badge").textContent =
        `${{handoff.from || "steward"}} -> ${{handoff.to || "complete"}}`;
    }}

    function renderTimeline(snapshot) {{
      const events = snapshot.events || [];
      const recent = events.slice(-30).reverse();
      document.getElementById("event-count").textContent = `${{events.length}} events`;
      document.getElementById("timeline").innerHTML = recent.map((event) => `
        <div class="event">
          <time>${{escapeHtml(event.at || "")}}</time>
          <div style="margin-top:6px"><strong>${{escapeHtml(event.event || "event")}}</strong></div>
          <pre class="payload">${{escapeHtml(shortJson(event.payload || {{}}, 1000))}}</pre>
        </div>
      `).join("") || `<div class="muted">No events yet.</div>`;
    }}

    function renderCheckpoints(snapshot) {{
      const checkpoints = snapshot.checkpoints || [];
      document.getElementById("checkpoint-count").textContent = `${{checkpoints.length}} checkpoints`;
      document.getElementById("checkpoints").innerHTML = checkpoints.map((checkpoint) => `
        <div class="checkpoint ${{replayCheckpoint?.name === checkpoint.name ? "active" : ""}}" data-checkpoint="${{escapeHtml(checkpoint.name || "")}}">
          <code>${{escapeHtml(checkpoint.name || "")}}</code>
          <div style="margin-top:8px">${{escapeHtml(checkpoint.handoff?.from || "steward")}} → ${{escapeHtml(checkpoint.handoff?.to || "complete")}}</div>
          <div class="muted" style="margin-top:6px">${{escapeHtml(shortText(checkpoint.handoff?.task || "no handoff task", 160))}}</div>
        </div>
      `).join("") || `<div class="muted">No checkpoints yet.</div>`;
      document.getElementById("json-state").textContent = JSON.stringify(snapshot.council_state || {{}}, null, 2);
      document.getElementById("task-root").textContent = snapshot.task_root || "No task loaded";
    }}

    function renderFocus(snapshot) {{
      const turns = snapshot.council_state?.turns || [];
      const decision = snapshot.council_state?.decision || {{}};
      const handoff = snapshot.council_state?.handoff || {{}};
      const focusSeat = selectedSeat || handoff.to || handoff.from || "bubba";
      const turn = turns.find((item) => item.agent === focusSeat);
      const isBubba = focusSeat === "bubba";
      document.getElementById("focus-seat-label").textContent = focusSeat;
      const role = seatMeta[focusSeat]?.label || "Seat";
      const html = isBubba
        ? `
          <div class="focus-name status-bubba">Bubba</div>
          <div class="focus-meta">Citadel · Final synthesis</div>
          <div class="focus-block"><strong>Decision</strong>${{escapeHtml(decision.summary || "(no summary yet)")}}</div>
          <div class="focus-block"><strong>Next Action</strong>${{escapeHtml(decision.next_action || "(not set)")}}</div>
          <div class="focus-block"><strong>Handoff</strong>${{escapeHtml(handoff.from || "steward")}} -> ${{escapeHtml(handoff.to || "complete")}}</div>
        `
        : `
          <div class="focus-name status-${{focusSeat}}">${{escapeHtml(focusSeat)}}</div>
          <div class="focus-meta">${{escapeHtml(role)}} district</div>
          <div class="focus-block"><strong>Key Point</strong>${{escapeHtml(turn?.key_point || "(no turn yet)")}}</div>
          <div class="focus-block"><strong>Risk</strong>${{escapeHtml(turn?.risk || "(not set)")}}</div>
          <div class="focus-block"><strong>Next Move</strong>${{escapeHtml(turn?.next_move || "(not set)")}}</div>
          <div class="focus-block"><strong>Confidence</strong>${{turn ? `${{turn.confidence}}%` : "waiting"}}</div>
        `;
      document.getElementById("focus-card").innerHTML = html;
    }}

    async function loadTasks() {{
      const res = await fetch("/api/tasks");
      const data = await res.json();
      const current = qsTask();
      taskSelect.innerHTML = `<option value="">Recent tasks</option>` + (data.tasks || []).map((task) =>
        `<option value="${{escapeHtml(task)}}" ${{task === current ? "selected" : ""}}>${{escapeHtml(task)}}</option>`
      ).join("");
    }}

    async function refresh() {{
      const taskId = qsTask();
      if (!taskId) {{
        document.getElementById("json-state").textContent = "Select a task.";
        return;
      }}
      const res = await fetch(`/api/task?task=${{encodeURIComponent(taskId)}}`);
      const data = await res.json();
      if (!res.ok) {{
        document.getElementById("json-state").textContent = data.error || "Failed to load task.";
        return;
      }}
      renderSnapshot(data);
    }}

    function renderSnapshot(data) {{
      lastSnapshot = data;
      const effective = replayCheckpoint
        ? {{
            ...data,
            council_state: replayCheckpoint.state || data.council_state,
            checkpoints: data.checkpoints,
          }}
        : data;
      const handoff = effective.council_state?.handoff || {{}};
      if (!selectedSeat) {{
        selectedSeat = handoff.to || handoff.from || "bubba";
      }}
      document.getElementById("replay-status").textContent = replayCheckpoint ? `Replay: ${{replayCheckpoint.name}}` : "Live mode";
      renderStats(effective);
      renderMap(effective);
      renderCitadel(effective);
      renderFocus(effective);
      renderTimeline(effective);
      renderCheckpoints(data);
    }}

    function installMapInteractions() {{
      [...seatOrder, "bubba"].forEach((seat) => {{
        const el = seat === "bubba" ? document.getElementById("citadel") : document.getElementById(`seat-${{seat}}`);
        if (!el) return;
        el.addEventListener("click", () => {{
          selectedSeat = seat;
          if (lastSnapshot) renderSnapshot(lastSnapshot);
        }});
      }});
      document.getElementById("checkpoints").addEventListener("click", (event) => {{
        const card = event.target.closest("[data-checkpoint]");
        if (!card || !lastSnapshot) return;
        const checkpoint = (lastSnapshot.checkpoints || []).find((item) => item.name === card.dataset.checkpoint);
        if (!checkpoint) return;
        replayCheckpoint = checkpoint;
        selectedSeat = checkpoint.handoff?.to || checkpoint.handoff?.from || selectedSeat;
        renderSnapshot(lastSnapshot);
      }});
      document.getElementById("citadel").addEventListener("dblclick", () => {{
        replayCheckpoint = null;
        if (lastSnapshot) renderSnapshot(lastSnapshot);
      }});
      document.getElementById("zoom-in").addEventListener("click", () => {{
        zoomLevel = Math.min(1.8, +(zoomLevel + 0.15).toFixed(2));
        applyCamera();
      }});
      document.getElementById("zoom-out").addEventListener("click", () => {{
        zoomLevel = Math.max(0.8, +(zoomLevel - 0.15).toFixed(2));
        applyCamera();
      }});
      document.getElementById("zoom-reset").addEventListener("click", () => {{
        zoomLevel = 1;
        panX = 0;
        panY = 0;
        applyCamera();
        replayCheckpoint = null;
        if (lastSnapshot) renderSnapshot(lastSnapshot);
      }});
      mapCamera.addEventListener("pointerdown", (event) => {{
        dragging = true;
        pointerId = event.pointerId;
        startX = event.clientX - panX;
        startY = event.clientY - panY;
        mapCamera.setPointerCapture(pointerId);
      }});
      mapCamera.addEventListener("pointermove", (event) => {{
        if (!dragging || event.pointerId !== pointerId) return;
        panX = event.clientX - startX;
        panY = event.clientY - startY;
        applyCamera();
      }});
      const stopDragging = () => {{
        dragging = false;
        pointerId = null;
      }};
      mapCamera.addEventListener("pointerup", stopDragging);
      mapCamera.addEventListener("pointercancel", stopDragging);
    }}

    function connectStream() {{
      const taskId = qsTask();
      clearReconnect();
      if (stream) {{
        stream.close();
        stream = null;
      }}
      if (!taskId) {{
        refreshStatus.textContent = "Select a task";
        return;
      }}
      stream = new EventSource(`/api/stream?task=${{encodeURIComponent(taskId)}}`);
      refreshStatus.textContent = "Connecting stream...";
      stream.addEventListener("open", () => {{
        reconnectDelayMs = 1000;
        clearReconnect();
        refreshStatus.textContent = "Streaming live";
      }});
      stream.addEventListener("snapshot", (event) => {{
        reconnectDelayMs = 1000;
        clearReconnect();
        renderSnapshot(JSON.parse(event.data));
      }});
      stream.addEventListener("error", async () => {{
        refreshStatus.textContent = "Stream interrupted";
        if (stream) {{
          stream.close();
          stream = null;
        }}
        scheduleReconnect();
      }});
    }}

    loadBtn.addEventListener("click", async () => {{
      setTask(taskInput.value.trim() || taskSelect.value);
      await loadTasks();
      await refresh();
      connectStream();
    }});

    taskSelect.addEventListener("change", async () => {{
      if (taskSelect.value) {{
        setTask(taskSelect.value);
        await refresh();
        connectStream();
      }}
    }});

    stateToggle.addEventListener("click", () => {{
      stateExpanded = !stateExpanded;
      applyStateView();
    }});

    (async () => {{
      installMapInteractions();
      applyStateView();
      applyCamera();
      await loadTasks();
      await refresh();
      connectStream();
      setInterval(loadTasks, 10000);
    }})();

    window.addEventListener("beforeunload", () => {{
      clearReconnect();
      if (stream) {{
        stream.close();
      }}
    }});
  </script>
</body>
</html>
"""
