from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agora.council_state import apply_turn_patch, build_initial_council_state, parse_structured_turn
from agora.forge.executor import inspect_worker
from agora.council_runtime import (
    _ensure_agent_lane_available,
    _expected_provider_for_agent,
    _parse_agent_output,
)
from agora.steward import Steward
from agora.transport import (
    configure_polling,
    configure_webhook,
    enable_funnel,
    inspect_telegram_webhook,
    load_transport_status,
)
from agora.viewer import build_task_snapshot, recent_task_ids


class StewardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.tempdir.name) / "runtime"
        self.workspace_root = Path(self.tempdir.name) / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.old_home = os.environ.get("AGORA_HOME")
        self.old_workspace = os.environ.get("AGORA_WORKSPACE_ROOT")
        os.environ["AGORA_HOME"] = str(self.runtime_root)
        os.environ["AGORA_WORKSPACE_ROOT"] = str(self.workspace_root)
        self.steward = Steward()

    def tearDown(self) -> None:
        if self.old_home is None:
            os.environ.pop("AGORA_HOME", None)
        else:
            os.environ["AGORA_HOME"] = self.old_home
        if self.old_workspace is None:
            os.environ.pop("AGORA_WORKSPACE_ROOT", None)
        else:
            os.environ["AGORA_WORKSPACE_ROOT"] = self.old_workspace
        self.tempdir.cleanup()

    def test_brief_creates_task_layout(self) -> None:
        result = self.steward.brief("Design the architecture for a Telegram router")
        task_root = Path(result["task_root"])
        self.assertTrue(task_root.exists())
        self.assertEqual(result["state"]["status"], "triaged")
        self.assertEqual(result["route"]["planning_lead"], "b2b2")
        self.assertEqual(result["route"]["chair"], "bubba")
        self.assertEqual(result["route"]["review_lead"], "karen")
        self.assertEqual(len(result["route"]["assigned_agents"]), 5)
        self.assertTrue((task_root / "brief.md").exists())
        self.assertTrue((task_root / "route.json").exists())
        self.assertTrue((task_root / "council" / "checkpoints").exists())

    def test_recent_tasks_lists_latest_first(self) -> None:
        first = self.steward.brief("First task")
        second = self.steward.brief("Second task")
        tasks = recent_task_ids(self.steward.paths)
        self.assertGreaterEqual(len(tasks), 2)
        self.assertEqual(tasks[0], second["task_id"])
        self.assertEqual(tasks[1], first["task_id"])

    def test_build_task_snapshot_includes_council_state(self) -> None:
        result = self.steward.brief("Snapshot task")
        snapshot = build_task_snapshot(self.steward.paths, result["task_id"])
        self.assertEqual(snapshot["task_id"], result["task_id"])
        self.assertEqual(snapshot["council_state"]["decision"]["owner"], "bubba")
        self.assertEqual(snapshot["checkpoints"], [])

    def test_execution_heavy_request_routes_to_myboy(self) -> None:
        result = self.steward.brief("Build and debug a media scraping worker on docker")
        self.assertEqual(result["route"]["planning_lead"], "myboy")
        self.assertEqual(result["route"]["assigned_workers"], ["forge-dellmac"])

    def test_run_records_artifacts(self) -> None:
        result = self.steward.brief("Implement a local smoke test")
        task_id = result["task_id"]
        run = self.steward.run(task_id, command="printf 'ok'", worker="forge-m2")
        self.assertEqual(run["returncode"], 0)
        artifacts = self.steward.artifacts(task_id)
        self.assertEqual(len(artifacts), 2)
        status = self.steward.status(task_id)
        self.assertEqual(status["state"]["status"], "verifying")

    def test_transport_status_reports_polling_by_default(self) -> None:
        config_path = Path(self.tempdir.name) / "openclaw.json"
        config_path.write_text(
            """
{
  "channels": {
    "telegram": {
      "enabled": true,
      "streaming": "partial"
    }
  }
}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        with patch(
            "agora.transport.inspect_tailscale",
            return_value={
                "installed": True,
                "app_installed": False,
                "binary": "/opt/homebrew/bin/tailscale",
                "source": "path",
                "daemon_reachable": False,
                "running": False,
                "version": "1.92.5",
                "backend_state": None,
                "auth_url": None,
                "logged_in": False,
                "dns_name": None,
                "candidate_url": None,
                "error": "failed to connect",
            },
        ):
            result = load_transport_status(config_path)
        self.assertEqual(result["telegram"]["mode"], "polling")
        self.assertFalse(result["tailscale"]["running"])

    def test_transport_webhook_configures_listener(self) -> None:
        config_path = Path(self.tempdir.name) / "openclaw.json"
        config_path.write_text(
            """
{
  "channels": {
    "telegram": {
      "enabled": true
    }
  }
}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        tailscale_status = {
            "installed": True,
            "app_installed": True,
            "binary": "/opt/homebrew/bin/tailscale",
            "source": "app",
            "daemon_reachable": True,
            "running": True,
            "version": "1.92.5",
            "backend_state": "Running",
            "auth_url": None,
            "logged_in": True,
            "dns_name": "m2mac.tail123.ts.net",
            "candidate_url": "https://m2mac.tail123.ts.net/telegram-webhook",
            "error": None,
        }
        with patch("agora.transport.inspect_tailscale", return_value=tailscale_status):
            result = configure_webhook("auto", config_path=config_path)
        self.assertEqual(result["telegram"]["mode"], "webhook")
        self.assertEqual(
            result["telegram"]["webhook_url"],
            "https://m2mac.tail123.ts.net/telegram-webhook",
        )
        self.assertTrue(result["telegram"]["webhook_secret_configured"])

    def test_transport_polling_clears_webhook_keys(self) -> None:
        config_path = Path(self.tempdir.name) / "openclaw.json"
        config_path.write_text(
            """
{
  "channels": {
    "telegram": {
      "enabled": true,
      "webhookUrl": "https://example.com/telegram-webhook",
      "webhookSecret": "secret",
      "webhookPath": "/telegram-webhook",
      "webhookHost": "127.0.0.1",
      "webhookPort": 8787
    }
  }
}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        with patch(
            "agora.transport.inspect_tailscale",
            return_value={
                "installed": False,
                "app_installed": False,
                "binary": None,
                "source": None,
                "daemon_reachable": False,
                "running": False,
                "version": None,
                "backend_state": None,
                "auth_url": None,
                "logged_in": False,
                "dns_name": None,
                "candidate_url": None,
                "error": "tailscale binary not found",
            },
        ):
            result = configure_polling(config_path=config_path)
        self.assertEqual(result["telegram"]["mode"], "polling")
        self.assertIsNone(result["telegram"]["webhook_url"])

    def test_enable_funnel_returns_approval_url_when_tailnet_blocks_it(self) -> None:
        tailscale_status = {
            "installed": True,
            "app_installed": True,
            "binary": "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
            "source": "app",
            "daemon_reachable": True,
            "running": True,
            "version": "1.94.2",
            "backend_state": "Running",
            "auth_url": None,
            "logged_in": True,
            "dns_name": "m2mac.tail123.ts.net",
            "candidate_url": "https://m2mac.tail123.ts.net/telegram-webhook",
            "error": None,
        }
        with patch("agora.transport.inspect_tailscale", return_value=tailscale_status):
            with patch("agora.transport._run_command") as run_command:
                run_command.return_value.returncode = 1
                run_command.return_value.stdout = """
Funnel is not enabled on your tailnet.
To enable, visit:

         https://login.tailscale.com/f/funnel?node=abc123
""".strip()
                run_command.return_value.stderr = ""
                result = enable_funnel(port=8787)
        self.assertFalse(result["enabled"])
        self.assertEqual(result["approval_url"], "https://login.tailscale.com/f/funnel?node=abc123")

    def test_inspect_telegram_webhook_reads_live_state(self) -> None:
        config_path = Path(self.tempdir.name) / "openclaw.json"
        config_path.write_text(
            """
{
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "123:abc",
      "webhookUrl": "https://m2mac.tail123.ts.net/telegram-webhook"
    }
  }
}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        response = MagicMock()
        response.read.return_value = json_bytes = (
            b'{"ok":true,"result":{"url":"https://m2mac.tail123.ts.net/telegram-webhook","pending_update_count":0,"ip_address":"1.2.3.4"}}'
        )
        del json_bytes
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("agora.transport.shutil.which", return_value=None):
            with patch("agora.transport.urlrequest.urlopen", return_value=response):
                result = inspect_telegram_webhook(config_path)
        self.assertTrue(result["reachable"])
        self.assertTrue(result["matches_configured_webhook"])
        self.assertEqual(result["pending_update_count"], 0)
        self.assertEqual(result["ip_address"], "1.2.3.4")

    def test_workers_status_reports_remote_shell_probe(self) -> None:
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "/usr/bin/bash\n"
        completed.stderr = ""
        with patch("agora.forge.executor._run_command", return_value=completed):
            result = inspect_worker("forge-dellmac")
        self.assertTrue(result["reachable"])
        self.assertEqual(result["shell"], "/usr/bin/bash")

    def test_doctor_aggregates_transport_and_workers(self) -> None:
        with patch(
            "agora.steward.service.load_transport_status",
            return_value={
                "telegram": {
                    "mode": "webhook",
                    "webhook_url": "https://m2mac.tail123.ts.net/telegram-webhook",
                },
                "tailscale": {
                    "running": True,
                },
            },
        ):
            with patch(
                "agora.steward.service.inspect_telegram_webhook",
                return_value={
                    "configured": True,
                    "reachable": True,
                    "url": "https://m2mac.tail123.ts.net/telegram-webhook",
                    "matches_configured_webhook": True,
                    "pending_update_count": 0,
                    "last_error_message": None,
                },
            ):
                with patch(
                    "agora.steward.service.inspect_workers",
                    return_value={
                        "ready": True,
                        "workers": [
                            {"name": "forge-m2", "reachable": True, "shell": "/bin/zsh"},
                            {"name": "forge-dellmac", "reachable": True, "shell": "/usr/bin/bash"},
                        ],
                        "issues": [],
                    },
                ):
                    result = self.steward.doctor()
        self.assertTrue(result["ready"])
        self.assertEqual(result["issues"], [])

    def test_cast_returns_named_council(self) -> None:
        result = self.steward.cast()
        self.assertEqual(result["chair"], "bubba")
        self.assertEqual([member["id"] for member in result["members"]], ["bubba", "b2b2", "myboy", "potna", "karen"])

    def test_convene_uses_council_runtime_and_updates_synthesis(self) -> None:
        brief = self.steward.brief("Design a council workflow")
        task_id = brief["task_id"]
        with patch(
            "agora.steward.service.run_council_session",
            return_value={
                "task_id": task_id,
                "order": ["b2b2", "karen", "bubba"],
                "turns": [
                    {"agent": "b2b2", "response": "innovation"},
                    {"agent": "karen", "response": "risks"},
                    {"agent": "bubba", "response": "final call"},
                ],
                "transcript_path": str(Path(brief["task_root"]) / "council" / "transcript.md"),
                "council_state": {
                    "task_id": task_id,
                    "chair": "bubba",
                    "decision": {
                        "verdict": "ship",
                        "summary": "final call",
                        "next_action": "implement schema",
                        "owner": "bubba",
                    },
                    "win_condition": "ship the council",
                    "leverage_patch": "json handoff",
                    "execution_guidance": "keep it tight",
                    "invariant_check": {"status": "pass", "notes": []},
                    "invariants": [],
                    "turns": [],
                },
            },
        ):
            result = self.steward.convene(task_id, agent_ids=["b2b2", "karen", "bubba"], timeout=30)
        self.assertEqual(result["status"], "reviewing")
        synthesis = (Path(brief["task_root"]) / "council" / "synthesis.md").read_text(encoding="utf-8")
        self.assertIn("ship", synthesis)
        self.assertIn("json handoff", synthesis)

    def test_convene_marks_task_blocked_when_council_runtime_fails(self) -> None:
        brief = self.steward.brief("Stress the council")
        task_id = brief["task_id"]
        with patch("agora.steward.service.run_council_session", side_effect=RuntimeError("b2b2 fell back")):
            with self.assertRaisesRegex(RuntimeError, "fell back"):
                self.steward.convene(task_id, agent_ids=["b2b2"], timeout=30)
        status = self.steward.status(task_id)
        self.assertEqual(status["state"]["status"], "blocked")
        events = self.steward.logs(task_id)["events"]
        self.assertTrue(any(event["event"] == "council.failed" for event in events))

    def test_parse_agent_output_tolerates_startup_noise(self) -> None:
        text, meta = _parse_agent_output('[plugins] startup\\n{"payloads":[{"text":"hello"}],"meta":{"durationMs":12}}')
        self.assertEqual(text, "hello")
        self.assertEqual(meta["durationMs"], 12)

    def test_parse_structured_turn_normalizes_fields(self) -> None:
        payload = parse_structured_turn(
            """
{
  "position": "Chair",
  "key_point": "Use a state object",
  "risk": "drift",
  "next_move": "write schema",
  "confidence": 120,
  "state_patch": {
    "win_condition": "ship faster",
    "minimum_viable_context": ["goal", "goal", "budget"],
    "invariant_check": {"status": "review", "notes": ["verify", "verify"]},
    "decision": {"verdict": "ship", "summary": "ready", "next_action": "build it"}
  }
}
""".strip()
        )
        self.assertEqual(payload["confidence"], 100)
        self.assertEqual(payload["state_patch"]["minimum_viable_context"], ["goal", "budget"])
        self.assertEqual(payload["state_patch"]["invariant_check"]["status"], "review")

    def test_parse_structured_turn_preserves_context_objects(self) -> None:
        payload = parse_structured_turn(
            """
{
  "position": "Planner",
  "key_point": "Keep schema typed",
  "risk": "stringified fields",
  "next_move": "preserve MVC objects",
  "confidence": 87,
  "state_patch": {
    "minimum_viable_context": [
      {"field": "task_id", "type": "string", "description": "task key"},
      "request_summary"
    ],
    "invariant_check": {"status": "pending", "notes": []},
    "decision": {"verdict": "pending", "summary": "", "next_action": ""}
  }
}
""".strip()
        )
        self.assertEqual(payload["state_patch"]["minimum_viable_context"][0]["field"], "task_id")
        self.assertEqual(payload["state_patch"]["minimum_viable_context"][1], "request_summary")

    def test_apply_turn_patch_merges_state(self) -> None:
        route = {
            "chair": "bubba",
            "council_order": ["myboy", "potna", "b2b2", "karen", "bubba"],
        }
        state = build_initial_council_state(
            task_id="agora-123",
            request_text="Build a council",
            route=route,
            agent_ids=route["council_order"],
        )
        merged = apply_turn_patch(
            state,
            {
                "agent": "karen",
                "name": "Karen",
                "provider": "google",
                "model": "gemini-2.5-flash",
                "duration_ms": 12,
                "structured": {
                    "position": "Risk Lead",
                    "key_point": "Need invariants",
                    "risk": "drift",
                    "next_move": "add checks",
                    "confidence": 88,
                    "state_patch": {
                        "win_condition": "",
                        "minimum_viable_context": ["goal"],
                        "momentum_vector": "",
                        "asymmetric_leverage": "",
                        "leverage_patch": "json patches",
                        "execution_guidance": "",
                        "invariants": ["budget"],
                        "invariant_check": {"status": "halt", "notes": ["missing budget"]},
                        "hard_halt": True,
                        "decision": {"verdict": "pending", "summary": "", "next_action": ""},
                    },
                },
            },
        )
        self.assertTrue(merged["hard_halt"])
        self.assertEqual(merged["decision"]["verdict"], "halt")
        self.assertEqual(merged["invariant_check"]["status"], "halt")
        self.assertEqual(merged["turns"][0]["agent"], "karen")
        self.assertEqual(merged["handoff"]["from"], "karen")
        self.assertEqual(merged["handoff"]["to"], "bubba")
        self.assertEqual(merged["handoff"]["task"], "add checks")

    def test_apply_turn_patch_merges_context_objects(self) -> None:
        route = {
            "chair": "bubba",
            "council_order": ["myboy", "potna", "b2b2", "karen", "bubba"],
        }
        state = build_initial_council_state(
            task_id="agora-typed",
            request_text="Build a typed council",
            route=route,
            agent_ids=route["council_order"],
        )
        merged = apply_turn_patch(
            state,
            {
                "agent": "myboy",
                "name": "Myboy",
                "provider": "google",
                "model": "gemini-2.5-flash",
                "duration_ms": 12,
                "structured": {
                    "position": "Execution Lead",
                    "key_point": "typed mvc",
                    "risk": "drift",
                    "next_move": "preserve objects",
                    "confidence": 88,
                    "state_patch": {
                        "win_condition": "",
                        "minimum_viable_context": [
                            {"field": "task_id", "type": "string", "description": "task key"}
                        ],
                        "momentum_vector": "",
                        "asymmetric_leverage": "",
                        "leverage_patch": "",
                        "execution_guidance": "",
                        "invariants": [],
                        "invariant_check": {"status": "pending", "notes": []},
                        "hard_halt": False,
                        "decision": {"verdict": "pending", "summary": "", "next_action": ""},
                    },
                },
            },
        )
        self.assertEqual(merged["minimum_viable_context"][0]["field"], "task_id")
        self.assertEqual(merged["handoff"]["from"], "myboy")
        self.assertEqual(merged["handoff"]["to"], "potna")

    def test_expected_provider_for_agent_reads_primary_model_provider(self) -> None:
        config_path = Path(self.tempdir.name) / "openclaw.json"
        config_path.write_text(
            """
{
  "agents": {
    "list": [
      {
        "id": "b2b2",
        "model": {
          "primary": "google/gemini-2.5-flash",
          "fallbacks": ["ollama/qwen2.5-7b-opt:latest"]
        }
      }
    ]
  }
}
""".strip()
            + "\n",
            encoding="utf-8",
        )
        with patch("agora.council_runtime.OPENCLAW_CONFIG_PATH", config_path):
            self.assertEqual(_expected_provider_for_agent("b2b2"), "google")

    def test_council_state_reads_structured_artifact(self) -> None:
        brief = self.steward.brief("Read council state")
        task_id = brief["task_id"]
        state_path = Path(brief["files"]["council_state"])
        state_path.write_text('{"task_id":"%s","decision":{"verdict":"ship"}}\n' % task_id, encoding="utf-8")
        self.assertEqual(self.steward.council_state(task_id)["decision"]["verdict"], "ship")

    def test_ensure_agent_lane_available_rejects_active_lock(self) -> None:
        agents_root = Path(self.tempdir.name) / "agents"
        sessions = agents_root / "b2b2" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / "busy.jsonl.lock").write_text('{"pid": 9999}\n', encoding="utf-8")
        with patch("agora.council_runtime.OPENCLAW_AGENTS_ROOT", agents_root):
            with patch("agora.council_runtime._pid_running", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "busy"):
                    _ensure_agent_lane_available("b2b2")


if __name__ == "__main__":
    unittest.main()
