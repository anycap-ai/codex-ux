#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


APP_NAME = "codex-ux-file-browser"
TRIGGERS = ("$codex-ux-file-browser", "/codex-ux-file-browser")
LOG_PATH = Path(tempfile.gettempdir()) / "codex-ux-file-browser-autostart.log"
LOCK_TIMEOUT_SECONDS = 8.0
PROMPT_TEXT_KEYS = {
    "content",
    "input",
    "message",
    "prompt",
    "text",
    "userinput",
    "usermessage",
    "userprompt",
}
MESSAGE_LIST_KEYS = {"conversation", "history", "messages", "transcript"}


def main() -> int:
    raw_prompt_payload = sys.stdin.read()
    if os.environ.get("CODEX_UX_FILE_BROWSER_AUTOSTART", "1") == "0":
        emit_continue()
        return 0
    if not should_trigger(raw_prompt_payload):
        emit_continue()
        return 0

    try:
        package_root = Path(__file__).resolve().parents[2]
        repo_root = find_repo_root(Path.cwd())
        launcher = find_launcher(package_root)
        if launcher is None:
            log("launcher not found")
            emit_continue()
            return 0

        thread_id = find_codex_thread_id(raw_prompt_payload)
        lock = acquire_hook_lock(repo_root, thread_id)
        if lock is None:
            log("could not acquire autostart lock")
            emit_continue()
            return 0
        try:
            startup = launch_review_browser(launcher, package_root, repo_root, thread_id)
            url = str(startup.get("url") or "").strip()
            if not url:
                log(f"launcher returned no url: {startup!r}")
                emit_continue()
                return 0

            opened = open_in_app_browser(launcher, url, thread_id)
            if not opened.get("ok"):
                log(f"browser automation failed: {opened}")
                emit_service_ready_context(startup, opened)
                return 0
            emit_opened_context(startup, opened)
        finally:
            release_hook_lock(lock)
    except Exception as exc:
        log(f"unexpected error: {type(exc).__name__}: {exc}")
        emit_continue()

    return 0


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def emit_continue() -> None:
    emit({"continue": True, "suppressOutput": True})


def emit_opened_context(startup: dict[str, Any], opened: dict[str, Any]) -> None:
    url = str(startup.get("url") or "").strip()
    snapshot_url = str(startup.get("snapshotUrl") or "").strip()
    workspace_root = str(startup.get("workspaceRoot") or "").strip()
    registry_path = str(startup.get("registryPath") or "").strip()
    session_path = str(startup.get("sessionPath") or "").strip()
    context = f"""Codex UX File Browser autostart hook succeeded.

The local review browser service is already running and the URL has already been opened in the Codex in-app browser by the hook. Do not run the Codex UX File Browser launcher again and do not open or navigate the in-app browser again for this startup step.

Use these values from the hook:
- url: {url}
- snapshotUrl: {snapshot_url}
- workspaceRoot: {workspace_root}
- registryPath: {registry_path}
- sessionPath: {session_path}

Continue with the Codex UX File Browser workflow from the point where the page is already open. When the user asks you to handle notes, read the snapshot from snapshotUrl or the active registry."""
    emit(
        {
            "continue": True,
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            },
        }
    )


def emit_service_ready_context(startup: dict[str, Any], opened: dict[str, Any]) -> None:
    url = str(startup.get("url") or "").strip()
    snapshot_url = str(startup.get("snapshotUrl") or "").strip()
    error = str(opened.get("error") or "unknown browser automation failure")
    browser_status = f"""The hook attempted browser automation, but did not confirm that the Codex in-app browser opened the URL.

Browser automation error: {error}

Open or navigate the Codex in-app browser to url if needed, then continue the normal Codex UX File Browser workflow."""

    context = f"""Codex UX File Browser autostart hook started the local review browser service.

Do not run the launcher again unless the URL health check fails. Reuse:
- url: {url}
- snapshotUrl: {snapshot_url}

{browser_status}"""
    emit(
        {
            "continue": True,
            "suppressOutput": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            },
        }
    )


def should_trigger(raw: str) -> bool:
    parsed = parse_json(raw)
    if isinstance(parsed, dict):
        text = "\n".join(current_prompt_text_values(parsed))
    elif isinstance(parsed, list):
        text = "\n".join(last_user_message_text(parsed))
    else:
        text = raw
    normalized = text.lower()
    return any(trigger in normalized for trigger in TRIGGERS)


def parse_json(raw: str) -> Any:
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def current_prompt_text_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key, value in payload.items():
        normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
        if normalized_key in PROMPT_TEXT_KEYS:
            values.extend(text_values(value))
        elif normalized_key in MESSAGE_LIST_KEYS and isinstance(value, list):
            values.extend(last_user_message_text(value))
    return values


def last_user_message_text(messages: list[Any]) -> list[str]:
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or message.get("author") or "").lower()
        if role and role != "user":
            continue
        values: list[str] = []
        for key, value in message.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized_key in PROMPT_TEXT_KEYS:
                values.extend(text_values(value))
        if values:
            return values
    return []


def text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(text_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for key, item in value.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            if normalized_key in PROMPT_TEXT_KEYS:
                values.extend(text_values(item))
        return values
    return []


def acquire_hook_lock(workspace_root: Path, thread_id: str):
    try:
        import fcntl
    except ImportError:
        return None

    key = hashlib.sha256(f"{workspace_root.resolve()}\n{thread_id}".encode("utf-8")).hexdigest()[:16]
    lock_path = Path(tempfile.gettempdir()) / "codex-ux-file-browser-autostart" / f"{key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w", encoding="utf-8")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            return handle
        except BlockingIOError:
            if time.monotonic() >= deadline:
                handle.close()
                return None
            time.sleep(0.1)


def release_hook_lock(handle) -> None:
    try:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass


def find_codex_thread_id(raw: str) -> str:
    env_thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if env_thread_id:
        return env_thread_id

    parsed = parse_json(raw)
    if not isinstance(parsed, (dict, list)):
        return ""
    return find_thread_id_in_json(parsed)


def find_thread_id_in_json(value: Any, key: str = "") -> str:
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            found = find_thread_id_in_json(item_value, str(item_key))
            if found:
                return found
        return ""
    if isinstance(value, list):
        for item in value:
            found = find_thread_id_in_json(item, key)
            if found:
                return found
        return ""
    if not isinstance(value, str):
        return ""

    text = value.strip()
    if not text:
        return ""

    from_url = thread_id_from_codex_url(text)
    if from_url:
        return from_url

    normalized_key = "".join(character for character in key.lower() if character.isalnum())
    if normalized_key in {"codexthreadid", "threadid", "thread"} or (
        "thread" in normalized_key and "id" in normalized_key
    ):
        return text
    return ""


def thread_id_from_codex_url(value: str) -> str:
    marker = "codex://threads/"
    index = value.find(marker)
    if index < 0:
        return ""
    thread_id = value[index + len(marker) :].split()[0].split('"')[0].split("'")[0]
    return thread_id.strip().rstrip("/")


def find_repo_root(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return cwd.resolve()


def find_launcher(package_root: Path) -> Path | None:
    for candidate in launcher_candidates(package_root):
        if candidate.is_file():
            return candidate
    return None


def launcher_candidates(package_root: Path) -> list[Path]:
    return [
        package_root / "skills/codex-ux-file-browser/scripts/launch.py",
        Path.home() / ".codex/skills/codex-ux-file-browser/scripts/launch.py",
    ]


def launch_review_browser(
    launcher: Path,
    package_root: Path,
    repo_root: Path,
    thread_id: str,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(launcher),
        str(repo_root),
    ]
    if should_reuse_active_browser(package_root, repo_root, launcher, thread_id):
        command.append("--reuse")
    else:
        log("skipping launcher --reuse because active browser is not reusable")
    command.extend(["--detach", "--json"])

    env = os.environ.copy()
    if thread_id:
        env["CODEX_THREAD_ID"] = thread_id

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"launcher exited {result.returncode}: {output}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("launcher did not return a JSON object")
    log(f"browser service ready: {payload.get('url')}")
    return payload


def should_reuse_active_browser(
    package_root: Path,
    repo_root: Path,
    selected_launcher: Path,
    thread_id: str,
) -> bool:
    local_launchers = [
        path.resolve()
        for path in launcher_candidates(package_root)[:2]
        if path.is_file()
    ]
    if local_launchers and selected_launcher.resolve() in local_launchers:
        allowed_launchers = local_launchers
    else:
        allowed_launchers = [selected_launcher.resolve()]

    payload = read_active_registry()
    if not payload or payload.get("app") != APP_NAME:
        return True
    try:
        active_workspace = Path(str(payload.get("workspaceRoot", ""))).resolve()
    except OSError:
        return False
    if active_workspace != repo_root.resolve():
        return True

    commands = active_browser_commands(payload)
    if not commands:
        return False

    if active_browser_thread_id(payload) != thread_id:
        log("active browser does not support this Codex automation context")
        return False

    allowed_text = [str(path) for path in allowed_launchers]
    for command in commands:
        if any(path_text in command for path_text in allowed_text):
            return True
    log(f"active browser is from non-preferred launcher: {' | '.join(commands)}")
    return False


def read_active_registry() -> dict[str, Any] | None:
    path = Path.home() / ".codex-ux/file-browser/active.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def active_browser_commands(payload: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    pid = payload.get("pid")
    if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit()):
        command = process_command(str(pid))
        if command:
            commands.append(command)

    port = port_from_url(str(payload.get("url") or ""))
    if port:
        for pid_value in listener_pids(port):
            command = process_command(pid_value)
            if command and command not in commands:
                commands.append(command)
    return commands


def active_browser_thread_id(payload: dict[str, Any]) -> str:
    pid = payload.get("pid")
    if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit()):
        return process_env_value(str(pid), "CODEX_THREAD_ID")
    return ""


def port_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    return str(parsed.port or "")


def listener_pids(port: str) -> list[str]:
    if not shutil.which("lsof"):
        return []
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    if result.returncode != 0:
        return []
    pids: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pids.append(line[1:])
    return pids


def process_command(pid: str) -> str:
    result = subprocess.run(
        ["ps", "-p", pid, "-o", "command="],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def process_env_value(pid: str, name: str) -> str:
    result = subprocess.run(
        ["ps", "eww", "-p", pid],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    if result.returncode != 0:
        return ""
    prefix = f"{name}="
    for token in result.stdout.split():
        if token.startswith(prefix):
            return token[len(prefix) :].strip()
    return ""


def open_in_app_browser(launcher: Path, url: str, thread_id: str) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"ok": False, "error": "in-app browser automation is only implemented for macOS"}
    if not shutil.which("swift"):
        return {"ok": False, "error": "swift is not available"}

    script = launcher.parent / "file_browser_server/codex_app_ax.swift"
    if not script.is_file():
        return {"ok": False, "error": f"Missing Codex AX automation script: {script}"}

    result = subprocess.run(
        ["swift", str(script), "open-browser", url, thread_id],
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    payload = parse_json((result.stdout or "").strip())
    if result.returncode != 0:
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("error") or "")
        message = message or (result.stderr or result.stdout or "").strip()
        return {"ok": False, "error": message, "returncode": result.returncode}
    if isinstance(payload, dict):
        return payload
    return {"ok": True}


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
