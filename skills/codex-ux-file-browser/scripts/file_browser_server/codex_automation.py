from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from .codex_host import CODEX_HOST_APP
from .swift_runtime import find_swift_runtime


CODEX_APP_AX_SCRIPT = Path(__file__).with_name("codex_app_ax.swift")
_AUTOMATION_LOCK = threading.Lock()


def trigger_codex_automation(prompt: str, codex_host: str) -> dict[str, Any]:
    if codex_host != CODEX_HOST_APP:
        return {
            "ok": False,
            "skipped": True,
            "codexHost": codex_host,
            "reason": "Codex app automation is disabled outside codex-app host mode",
        }

    if not _AUTOMATION_LOCK.acquire(blocking=False):
        return {"ok": False, "codexHost": codex_host, "error": "Codex automation is already running"}

    try:
        return run_codex_automation(prompt, codex_host)
    finally:
        _AUTOMATION_LOCK.release()


def run_codex_automation(prompt: str, codex_host: str) -> dict[str, Any]:
    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not CODEX_APP_AX_SCRIPT.is_file():
        return {"ok": False, "codexHost": codex_host, "error": f"Missing Codex automation script: {CODEX_APP_AX_SCRIPT}"}

    env = os.environ.copy()
    env["CODEX_AUTOMATION_PROMPT"] = prompt
    env["CODEX_AUTOMATION_THREAD_ID"] = thread_id
    runtime = find_swift_runtime(env)
    if runtime is None:
        return {"ok": False, "codexHost": codex_host, "error": "swift is not available"}

    try:
        result = subprocess.run(
            [runtime.command, str(CODEX_APP_AX_SCRIPT), "send-prompt"],
            capture_output=True,
            text=True,
            env=runtime.env,
            timeout=12,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return with_thread_id(
            {"ok": False, "codexHost": codex_host, "error": "Timed out while trying to automate Codex"},
            thread_id,
        )

    payload = parse_json_object((result.stdout or "").strip())
    if result.returncode != 0:
        error = payload.get("error") if isinstance(payload.get("error"), str) else None
        message = error or (result.stderr or result.stdout or "Codex automation failed").strip()
        return with_thread_id(
            {"ok": False, "codexHost": codex_host, "error": message, "returncode": result.returncode},
            thread_id,
        )
    if not payload.get("ok"):
        message = payload.get("error") if isinstance(payload.get("error"), str) else "Codex automation failed"
        return with_thread_id({"ok": False, "codexHost": codex_host, "error": message, **payload}, thread_id)
    return with_thread_id({"codexHost": codex_host, **payload}, thread_id)


def with_thread_id(payload: dict[str, Any], thread_id: str) -> dict[str, Any]:
    if thread_id:
        return {**payload, "threadId": thread_id}
    return payload


def parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}
