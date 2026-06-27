from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any, Iterator
from urllib.error import URLError
from urllib.request import urlopen

from .codex_host import CODEX_HOST_CLI, detect_codex_host
from .workspace_registry import workspace_registry_path
from .config import WORKSPACE_LOCK_DIR
from .http_app import create_server
from .protocol import APP_NAME, SCHEMA_STARTUP, workspace_key
from .utils import utc_now

try:
    import fcntl
except ImportError:  # pragma: no cover - fcntl is unavailable on Windows.
    fcntl = None


def main() -> None:
    args = parse_args()
    codex_host = detect_codex_host()
    open_browser = args.open_browser or codex_host.host == CODEX_HOST_CLI

    workspace_root = Path(args.workspace).expanduser().resolve()
    if not workspace_root.is_dir():
        raise SystemExit(f"Workspace root is not a directory: {workspace_root}")

    if args.detach:
        with workspace_launch_lock(workspace_root):
            if args.reuse:
                reusable = find_live_registry(workspace_root, codex_host.host)
                if reusable:
                    open_startup_url(reusable, open_browser)
                    output_startup_payload(reusable, args.json)
                    return

            payload = start_detached(workspace_root, args.host, args.port, codex_host.host)
            open_startup_url(payload, open_browser)
            output_startup_payload(payload, args.json)
            return

    if args.reuse:
        with workspace_launch_lock(workspace_root):
            reusable = find_live_registry(workspace_root, codex_host.host)
        if reusable:
            open_startup_url(reusable, open_browser)
            output_startup_payload(reusable, args.json)
            return

    run_foreground(
        workspace_root,
        args.host,
        args.port,
        args.json,
        codex_host.host,
        codex_host.source,
        open_browser,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Codex UX local file browser.")
    parser.add_argument("workspace", nargs="?", default=os.getcwd(), help="Workspace root to review")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", default=0, type=int, help="Bind port. Use 0 for a random available port.")
    parser.add_argument("--reuse", action="store_true", help="Reuse a healthy active browser for this workspace.")
    parser.add_argument("--detach", action="store_true", help="Start the server in the background and exit.")
    parser.add_argument("--json", action="store_true", help="Print one JSON object with startup details.")
    parser.add_argument("--open", dest="open_browser", action="store_true", help="Open the browser URL after launch.")
    return parser.parse_args()


@contextmanager
def workspace_launch_lock(workspace_root: Path) -> Iterator[None]:
    WORKSPACE_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = WORKSPACE_LOCK_DIR / f"{workspace_key(workspace_root)}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def run_foreground(
    workspace_root: Path,
    host: str,
    port: int,
    json_output: bool,
    codex_host: str,
    codex_host_source: str,
    open_browser: bool,
) -> None:
    server, base_url, state = create_server(
        workspace_root,
        host,
        port,
        codex_host,
        codex_host_source,
    )
    payload = build_startup_payload(state, base_url, reused=False, detached=False)
    output_startup_payload(payload, json_output)
    open_startup_url(payload, open_browser)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_detached(workspace_root: Path, host: str, port: int, codex_host: str) -> dict[str, Any]:
    log_path = detached_log_path(workspace_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    launcher = Path(sys.argv[0]).resolve()
    command = [
        sys.executable,
        str(launcher),
        str(workspace_root),
        "--host",
        host,
        "--port",
        str(port),
        "--json",
    ]
    popen_options: dict[str, Any] = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        **popen_options,
    )
    log_file.close()
    payload = wait_for_detached_server(workspace_root, process, log_path, codex_host)
    payload["detached"] = True
    payload["reused"] = False
    payload["pid"] = process.pid
    payload["logPath"] = str(log_path)
    return payload


def wait_for_detached_server(
    workspace_root: Path,
    process: subprocess.Popen[str],
    log_path: Path,
    codex_host: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"Detached file browser exited early with code {process.returncode}. Log: {log_path}")
        payload = read_workspace_registry(workspace_root)
        if payload and payload.get("pid") == process.pid:
            live = live_registry_payload(workspace_root, payload, codex_host)
            if live:
                return live
        time.sleep(0.1)
    raise SystemExit(f"Timed out waiting for detached file browser. Log: {log_path}")


def find_live_registry(workspace_root: Path, codex_host: str) -> dict[str, Any] | None:
    payload = read_workspace_registry(workspace_root)
    live = live_registry_payload(workspace_root, payload, codex_host) if payload else None
    if not live:
        return None
    live["reused"] = True
    live["detached"] = False
    return live


def live_registry_payload(workspace_root: Path, payload: dict[str, Any], codex_host: str) -> dict[str, Any] | None:
    if payload.get("app") != APP_NAME:
        return None
    if payload.get("codexHost") != codex_host:
        return None
    if Path(str(payload.get("workspaceRoot", ""))).resolve() != workspace_root:
        return None

    url = str(payload.get("url") or "").rstrip("/")
    if not url:
        return None
    meta = request_json(f"{url}/api/meta")
    if not isinstance(meta, dict):
        return None
    if meta.get("app") != APP_NAME:
        return None
    if meta.get("codexHost") != codex_host:
        return None
    if Path(str(meta.get("workspaceRoot", ""))).resolve() != workspace_root:
        return None

    result = dict(payload)
    result["activeSchemaVersion"] = payload.get("schemaVersion")
    result["schemaVersion"] = SCHEMA_STARTUP
    result["url"] = url
    result["snapshotUrl"] = str(payload.get("snapshotUrl") or f"{url}/snapshot.json")
    registry_path = payload.get("registryPath")
    if not isinstance(registry_path, str) or not registry_path:
        return None
    result["registryPath"] = registry_path
    result["healthy"] = True
    result["checkedAt"] = utc_now()
    return result


def read_workspace_registry(workspace_root: Path) -> dict[str, Any] | None:
    return read_registry(workspace_registry_path(workspace_root))


def read_registry(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def request_json(url: str) -> Any:
    try:
        with urlopen(url, timeout=0.5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return None


def build_startup_payload(state, base_url: str, reused: bool, detached: bool) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_STARTUP,
        "app": APP_NAME,
        "codexHost": state.codex_host,
        "codexHostSource": state.codex_host_source,
        "workspaceRoot": str(state.workspace_root),
        "sessionId": state.session.get("sessionId"),
        "sessionPath": str(state.session_path),
        "snapshotUrl": f"{base_url}/snapshot.json",
        "url": base_url,
        "registryPath": str(workspace_registry_path(state.workspace_root)),
        "pid": os.getpid(),
        "reused": reused,
        "detached": detached,
        "healthy": True,
        "startedAt": utc_now(),
    }


def output_startup_payload(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2), flush=True)
        return

    print("Codex UX File Browser", flush=True)
    print(f"Codex host: {payload['codexHost']} ({payload.get('codexHostSource', 'unknown')})", flush=True)
    print(f"Workspace: {payload['workspaceRoot']}", flush=True)
    print(f"URL: {payload['url']}", flush=True)
    print(f"Snapshot: {payload['snapshotUrl']}", flush=True)
    print(f"Session: {payload['sessionPath']}", flush=True)
    print(f"Registry: {payload['registryPath']}", flush=True)
    if payload.get("reused"):
        print("Reused: true", flush=True)
    if payload.get("detached"):
        print(f"Detached: true (pid {payload['pid']})", flush=True)
        print(f"Log: {payload['logPath']}", flush=True)


def detached_log_path(workspace_root: Path) -> Path:
    root_key = workspace_key(workspace_root.resolve())
    return Path(tempfile.gettempdir()) / "codex-ux-file-browser" / f"{root_key}.log"


def open_startup_url(payload: dict[str, Any], enabled: bool) -> None:
    if not enabled:
        return
    url = str(payload.get("url") or "").strip()
    if not url:
        return
    try:
        if not webbrowser.open(url):
            print(f"Could not open browser automatically: {url}", file=sys.stderr, flush=True)
    except Exception as error:
        print(f"Could not open browser automatically: {error}", file=sys.stderr, flush=True)
