from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit, urlunsplit

DEFAULT_OPENCLAW_CONFIG = Path.home() / ".openclaw" / "openclaw.json"
DEFAULT_WEBHOOK_PATH = "/telegram-webhook"
DEFAULT_WEBHOOK_HOST = "127.0.0.1"
DEFAULT_WEBHOOK_PORT = 8787
TAILSCALE_APP_CLI = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
FUNNEL_APPROVAL_URL_RE = re.compile(r"https://login\.tailscale\.com/\S+")
TELEGRAM_API_TIMEOUT = 5


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _ensure_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _clean_dns_name(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip(".")


def _run_command(
    args: list[str],
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _clean_command_output(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    sanitized = value.replace("\r", "")
    sanitized = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", sanitized)
    return sanitized.strip()


def _tailscale_candidates() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if TAILSCALE_APP_CLI.exists():
        candidates.append(("app", str(TAILSCALE_APP_CLI)))
    binary = shutil.which("tailscale")
    if binary:
        candidates.append(("path", binary))
    return candidates


def inspect_tailscale(webhook_path: str = DEFAULT_WEBHOOK_PATH) -> dict[str, Any]:
    candidates = _tailscale_candidates()
    status: dict[str, Any] = {
        "installed": len(candidates) > 0,
        "app_installed": TAILSCALE_APP_CLI.exists(),
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
        "error": None,
    }
    if not candidates:
        status["error"] = "tailscale binary not found"
        return status

    errors: list[str] = []
    for source, binary in candidates:
        version_result = _run_command([binary, "version"], timeout=5)
        version = None
        if version_result.returncode == 0:
            first_line = version_result.stdout.strip().splitlines()
            if first_line:
                version = first_line[0].strip()

        try:
            status_result = _run_command([binary, "status", "--json"], timeout=5)
        except subprocess.TimeoutExpired:
            errors.append(f"{source}:tailscale status timed out")
            continue
        if status_result.returncode != 0:
            detail = (status_result.stderr or status_result.stdout).strip() or "tailscale status failed"
            errors.append(f"{source}:{detail}")
            continue

        payload = json.loads(status_result.stdout)
        self_info = payload.get("Self") or {}
        dns_name = _clean_dns_name(self_info.get("DNSName"))
        backend_state = payload.get("BackendState")
        auth_url = payload.get("AuthURL")
        status["binary"] = binary
        status["source"] = source
        status["version"] = payload.get("Version") or version
        status["daemon_reachable"] = True
        status["running"] = True
        status["backend_state"] = backend_state
        status["auth_url"] = auth_url
        status["logged_in"] = backend_state not in {"NeedsLogin", "LoggedOut", "NoState"}
        status["dns_name"] = dns_name
        if dns_name:
            status["candidate_url"] = f"https://{dns_name}{webhook_path}"
        status["error"] = None
        return status

    status["error"] = "; ".join(errors) if errors else "tailscale status failed"
    return status


def _resolve_webhook_url(requested_url: str, *, webhook_path: str) -> tuple[str, str]:
    parsed = urlsplit(requested_url.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError("Webhook URL must use https://")
    if not parsed.netloc:
        raise ValueError("Webhook URL must include a host.")
    if parsed.query or parsed.fragment:
        raise ValueError("Webhook URL must not include query params or fragments.")
    resolved_path = parsed.path if parsed.path and parsed.path != "/" else webhook_path
    if not resolved_path.startswith("/"):
        resolved_path = f"/{resolved_path}"
    final_url = urlunsplit((parsed.scheme, parsed.netloc, resolved_path, "", ""))
    return final_url, resolved_path


def load_transport_status(config_path: Path | None = None) -> dict[str, Any]:
    resolved_config = (config_path or DEFAULT_OPENCLAW_CONFIG).expanduser()
    payload = _load_json(resolved_config)
    channels = payload.get("channels") if isinstance(payload.get("channels"), dict) else {}
    telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
    webhook_path = str(telegram.get("webhookPath") or DEFAULT_WEBHOOK_PATH)
    webhook_host = str(telegram.get("webhookHost") or DEFAULT_WEBHOOK_HOST)
    webhook_port = int(telegram.get("webhookPort") or DEFAULT_WEBHOOK_PORT)
    webhook_url = str(telegram.get("webhookUrl") or "").strip()
    mode = "webhook" if webhook_url else "polling"
    tailscale = inspect_tailscale(webhook_path=webhook_path)

    next_steps: list[str] = []
    if mode == "polling":
        if tailscale.get("backend_state") == "NeedsLogin" and tailscale.get("auth_url"):
            next_steps.append(f"Authenticate this node in Tailscale: {tailscale['auth_url']}")
            next_steps.append("Once authenticated, rerun `python3 -m agora transport-status --json` to confirm a DNS name.")
        elif tailscale["running"] and tailscale["candidate_url"]:
            next_steps.append(f"Publish the local listener with `tailscale funnel --bg {webhook_port}`.")
            next_steps.append(
                f"Switch Agora to webhook mode with `python3 -m agora transport-webhook --url {tailscale['candidate_url']}`."
            )
        elif tailscale.get("app_installed") and not tailscale.get("daemon_reachable"):
            next_steps.append("Launch the Tailscale app and complete its onboarding so the app CLI can answer status requests.")
        elif tailscale["installed"]:
            next_steps.append("Start Tailscale on the M2 and bring the node online before enabling webhook mode.")
            next_steps.append("Once it is online, publish the listener with `tailscale funnel --bg 8787`.")
        else:
            next_steps.append("Provide a public HTTPS endpoint or reverse proxy before switching Telegram to webhook mode.")
    else:
        if tailscale["running"]:
            next_steps.append("Run `python3 -m agora doctor --json` to confirm the live Telegram webhook still matches config.")
            next_steps.append(f"Ensure the public ingress still forwards to `{webhook_host}:{webhook_port}`.")
        else:
            next_steps.append("Bring up the ingress host before expecting webhook delivery.")

    return {
        "config_path": str(resolved_config),
        "telegram": {
            "enabled": bool(telegram.get("enabled")),
            "mode": mode,
            "streaming": telegram.get("streaming", "partial"),
            "webhook_url": webhook_url or None,
            "webhook_secret_configured": bool(str(telegram.get("webhookSecret") or "").strip()),
            "webhook_path": webhook_path,
            "webhook_host": webhook_host,
            "webhook_port": webhook_port,
            "timeout_seconds": telegram.get("timeoutSeconds"),
            "network": telegram.get("network") if isinstance(telegram.get("network"), dict) else {},
            "retry": telegram.get("retry") if isinstance(telegram.get("retry"), dict) else {},
        },
        "tailscale": tailscale,
        "next_steps": next_steps,
    }


def inspect_telegram_webhook(config_path: Path | None = None) -> dict[str, Any]:
    resolved_config = (config_path or DEFAULT_OPENCLAW_CONFIG).expanduser()
    payload = _load_json(resolved_config)
    channels = payload.get("channels") if isinstance(payload.get("channels"), dict) else {}
    telegram = channels.get("telegram") if isinstance(channels.get("telegram"), dict) else {}
    bot_token = str(telegram.get("botToken") or "").strip()
    configured_url = str(telegram.get("webhookUrl") or "").strip() or None

    status = {
        "configured": bool(bot_token),
        "reachable": False,
        "url": None,
        "has_custom_certificate": None,
        "pending_update_count": None,
        "ip_address": None,
        "last_error_date": None,
        "last_error_message": None,
        "max_connections": None,
        "matches_configured_webhook": None,
        "error": None,
    }
    if not bot_token:
        status["error"] = "telegram bot token missing from config"
        return status

    request_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    payload: dict[str, Any]
    curl_binary = shutil.which("curl")
    if curl_binary:
        try:
            result = _run_command(
                [curl_binary, "-4", "-sS", "--max-time", str(TELEGRAM_API_TIMEOUT), request_url],
                timeout=TELEGRAM_API_TIMEOUT + 1,
            )
        except subprocess.TimeoutExpired:
            status["error"] = "telegram api timed out"
            return status
        if result.returncode != 0:
            status["error"] = "telegram api unreachable"
            return status
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            status["error"] = "telegram api returned invalid JSON"
            return status
    else:
        try:
            with urlrequest.urlopen(request_url, timeout=TELEGRAM_API_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urlerror.HTTPError as exc:
            status["error"] = f"telegram api returned HTTP {exc.code}"
            return status
        except urlerror.URLError:
            status["error"] = "telegram api unreachable"
            return status
        except TimeoutError:
            status["error"] = "telegram api timed out"
            return status
        except Exception as exc:  # pragma: no cover - defensive safety net
            status["error"] = f"telegram api error: {exc.__class__.__name__}"
            return status

    if not payload.get("ok"):
        status["error"] = "telegram api rejected webhook inspection"
        return status

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    live_url = str(result.get("url") or "").strip() or None
    status.update(
        {
            "reachable": True,
            "url": live_url,
            "has_custom_certificate": bool(result.get("has_custom_certificate")),
            "pending_update_count": result.get("pending_update_count"),
            "ip_address": result.get("ip_address"),
            "last_error_date": result.get("last_error_date"),
            "last_error_message": result.get("last_error_message"),
            "max_connections": result.get("max_connections"),
            "matches_configured_webhook": live_url == configured_url,
        }
    )
    return status


def configure_webhook(
    public_url: str,
    *,
    config_path: Path | None = None,
    webhook_host: str = DEFAULT_WEBHOOK_HOST,
    webhook_port: int = DEFAULT_WEBHOOK_PORT,
    webhook_path: str = DEFAULT_WEBHOOK_PATH,
    secret_value: str | None = None,
) -> dict[str, Any]:
    resolved_config = (config_path or DEFAULT_OPENCLAW_CONFIG).expanduser()
    payload = _load_json(resolved_config)
    channels = _ensure_mapping(payload, "channels")
    telegram = _ensure_mapping(channels, "telegram")

    tailscale = inspect_tailscale(webhook_path=webhook_path)
    chosen_url = public_url.strip()
    if chosen_url.lower() in {"auto", "tailscale"}:
        chosen_url = str(tailscale.get("candidate_url") or "").strip()
        if not chosen_url:
            raise RuntimeError("Tailscale is not online, so Agora could not derive a public webhook URL.")

    final_url, final_path = _resolve_webhook_url(chosen_url, webhook_path=webhook_path)
    generated_secret = secret_value is None
    telegram["webhookUrl"] = final_url
    telegram["webhookSecret"] = secret_value or secrets.token_urlsafe(24)
    telegram["webhookPath"] = final_path
    telegram["webhookHost"] = webhook_host
    telegram["webhookPort"] = int(webhook_port)
    telegram["streaming"] = telegram.get("streaming") or "partial"

    network = _ensure_mapping(telegram, "network")
    if "autoSelectFamily" not in network:
        network["autoSelectFamily"] = True
    if "dnsResultOrder" not in network:
        network["dnsResultOrder"] = "ipv4first"

    _write_json(resolved_config, payload)
    status = load_transport_status(resolved_config)
    status["changed"] = True
    status["restart_required"] = True
    status["generated_secret"] = generated_secret
    return status


def configure_polling(config_path: Path | None = None) -> dict[str, Any]:
    resolved_config = (config_path or DEFAULT_OPENCLAW_CONFIG).expanduser()
    payload = _load_json(resolved_config)
    channels = _ensure_mapping(payload, "channels")
    telegram = _ensure_mapping(channels, "telegram")

    for key in ("webhookUrl", "webhookSecret", "webhookPath", "webhookHost", "webhookPort"):
        telegram.pop(key, None)

    _write_json(resolved_config, payload)
    status = load_transport_status(resolved_config)
    status["changed"] = True
    status["restart_required"] = True
    return status


def enable_funnel(port: int = DEFAULT_WEBHOOK_PORT) -> dict[str, Any]:
    tailscale = inspect_tailscale()
    binary = tailscale.get("binary")
    if not binary:
        raise RuntimeError(tailscale.get("error") or "Tailscale is not installed.")
    if tailscale.get("backend_state") == "NeedsLogin":
        raise RuntimeError(
            f"Tailscale needs login before Funnel can be enabled. Auth URL: {tailscale.get('auth_url') or '(unknown)'}"
        )

    script_log_path: Path | None = None
    timed_out = False
    try:
        command = [str(binary), "funnel", "--bg", str(port)]
        if tailscale.get("source") == "app" and shutil.which("script"):
            handle = tempfile.NamedTemporaryFile(prefix="agora-funnel-", suffix=".log", delete=False)
            handle.close()
            script_log_path = Path(handle.name)
            command = ["script", "-q", str(script_log_path), *command]
        result = _run_command(command, timeout=15)
        stdout = _clean_command_output(result.stdout)
        stderr = _clean_command_output(result.stderr)
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = _clean_command_output(exc.stdout if isinstance(exc.stdout, str) else "")
        stderr = _clean_command_output(exc.stderr if isinstance(exc.stderr, str) else "")
        returncode = None
    finally:
        transcript = ""
        if script_log_path and script_log_path.exists():
            transcript = _clean_command_output(script_log_path.read_text(encoding="utf-8", errors="ignore"))
            script_log_path.unlink(missing_ok=True)
        if transcript:
            if stdout:
                stdout = "\n".join(part for part in (stdout, transcript) if part)
            else:
                stdout = transcript

    combined = "\n".join(
        part.strip()
        for part in (stdout, stderr)
        if isinstance(part, str) and part.strip()
    ).strip()
    approval_match = FUNNEL_APPROVAL_URL_RE.search(combined)
    approval_url = approval_match.group(0) if approval_match else None
    enabled = returncode == 0

    next_steps: list[str] = []
    if enabled and tailscale.get("candidate_url"):
        next_steps.append(
            f"Switch Agora to webhook mode with `python3 -m agora transport-webhook --url {tailscale['candidate_url']}`."
        )
        next_steps.append("Restart the OpenClaw gateway after the webhook config write.")
    elif approval_url:
        next_steps.append(f"Enable Funnel for this node: {approval_url}")
        next_steps.append(f"Rerun `python3 -m agora transport-funnel --port {port}` after approval.")
    elif timed_out:
        next_steps.append("The Funnel command timed out while waiting for Tailscale. Check the app UI, then rerun the command.")
    else:
        next_steps.append("Resolve the Funnel error, then rerun the command.")

    return {
        "operation": "funnel",
        "tailscale": tailscale,
        "port": int(port),
        "enabled": enabled,
        "approval_url": approval_url,
        "candidate_url": tailscale.get("candidate_url"),
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "next_steps": next_steps,
    }
