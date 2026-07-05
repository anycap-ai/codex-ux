from __future__ import annotations

import json
import posixpath
import shutil
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .workspace_registry import write_registry_files
from .codex_automation import trigger_codex_automation
from .config import DIST_DIR, LIMITS
from .handoff import build_handoff_payload, write_handoff_files
from .protocol import APP_NAME, SCHEMA_SNAPSHOT, build_surface
from .scan import should_skip_file
from .search import search_workspace
from .state import ReviewState
from .utils import clamp_int, first, image_mime, is_relative_to, mime_for, require_path


class ReviewHandler(SimpleHTTPRequestHandler):
    state: ReviewState
    base_url: str

    server_version = "AgentUXFileReviewer/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            route = parsed.path

            if route == "/api/meta":
                self.send_json(
                    {
                        "app": APP_NAME,
                        "schemaVersion": SCHEMA_SNAPSHOT,
                        "codexHost": self.state.codex_host,
                        "codexHostSource": self.state.codex_host_source,
                        "surface": build_surface(self.state.workspace_root),
                        "workspaceRoot": str(self.state.workspace_root),
                        "sessionPath": str(self.state.session_path),
                        "maxTextBytes": LIMITS.max_text_bytes,
                        "maxImageBytes": LIMITS.max_image_bytes,
                        "maxIntentBodyChars": LIMITS.max_intent_body_chars,
                    }
                )
                return

            if route == "/api/files":
                self.send_json({"workspaceRoot": str(self.state.workspace_root), "files": self.state.get_files()})
                return

            if route == "/api/file":
                self.serve_file(query)
                return

            if route == "/api/file/status":
                self.serve_file_status(query)
                return

            if route == "/api/image":
                self.serve_image(query)
                return

            if route.startswith("/api/raw/"):
                self.serve_workspace_resource(route.removeprefix("/api/raw/"))
                return

            if route == "/api/search":
                search_query = first(query, "q").strip()
                limit = clamp_int(first(query, "limit"), 1, 300, 80)
                results = search_workspace(self.state, search_query, limit) if search_query else []
                self.send_json({"query": search_query, "results": results})
                return

            if route == "/api/session":
                self.send_json(self.state.session)
                return

            if route == "/snapshot.json":
                open_only = first(query, "intents").lower() in {"active", "open"}
                self.send_json(self.state.build_snapshot(open_only=open_only))
                return

            self.serve_static(route)
        except Exception as error:
            self.send_exception_json(error)

    def do_PUT(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/session":
                body = self.read_json_body()
                self.state.session = self.state.sanitize_session(body)
                self.state.save_session()
                self.send_json(self.state.session)
                return

            if parsed.path == "/api/file":
                result = self.state.save_text_file(self.read_json_body())
                status = HTTPStatus.CONFLICT if result.get("conflict") else HTTPStatus.OK
                self.send_json(result, status)
                return

            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as error:
            self.send_exception_json(error)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/intents/resolve":
                body = self.read_json_body()
                ids = body.get("ids")
                if not isinstance(ids, list) or not all(isinstance(intent_id, str) for intent_id in ids):
                    self.send_json({"error": "Expected JSON body with string array: ids"}, HTTPStatus.BAD_REQUEST)
                    return
                self.send_json(self.state.resolve_intents(ids))
                return

            if parsed.path != "/api/handoff/send":
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

            self.read_json_body()
            handoff = build_handoff_payload(self.state, self.base_url)
            write_handoff_files(self.state, handoff)
            automation = trigger_codex_automation(handoff["prompt"], self.state.codex_host)
            response = {
                **handoff,
                "sent": automation["ok"],
                "automation": automation,
            }
            self.send_json(response)
        except Exception as error:
            self.send_exception_json(error)

    def serve_file(self, query: dict[str, list[str]]) -> None:
        relative_path = require_path(query)
        absolute_path = self.state.safe_resolve(relative_path)
        file_info = self.state.text_file_metadata(relative_path, absolute_path, include_hash=True)
        content = absolute_path.read_text("utf-8")
        self.send_json(
            {
                "file": file_info,
                "content": content,
            }
        )

    def serve_file_status(self, query: dict[str, list[str]]) -> None:
        relative_path = require_path(query)
        self.send_json({"file": self.state.text_file_status(relative_path)})

    def serve_image(self, query: dict[str, list[str]]) -> None:
        relative_path = require_path(query)
        absolute_path = self.state.safe_resolve(relative_path)
        stat_result = absolute_path.stat()
        if stat_result.st_size > LIMITS.max_image_bytes:
            self.send_json({"error": "Image is too large for review"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        mime = image_mime(absolute_path)
        if not mime:
            self.send_json({"error": "Unsupported image type"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with absolute_path.open("rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def serve_workspace_resource(self, raw_path: str) -> None:
        relative_path = unquote(raw_path).lstrip("/")
        absolute_path = self.state.safe_resolve(relative_path)
        if not absolute_path.exists() or not absolute_path.is_file():
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if should_skip_file(absolute_path.name, relative_path):
            self.send_json({"error": "Resource is not reviewable"}, HTTPStatus.FORBIDDEN)
            return
        max_bytes = LIMITS.max_pdf_bytes if absolute_path.suffix.lower() == ".pdf" else LIMITS.max_image_bytes
        if absolute_path.stat().st_size > max_bytes:
            self.send_json({"error": "Resource is too large for preview"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", mime_for(absolute_path))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "script-src 'none'; object-src 'none'; connect-src 'none'")
        self.end_headers()
        with absolute_path.open("rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def serve_static(self, route: str) -> None:
        if route == "/":
            route = "/index.html"
        clean_path = posixpath.normpath(unquote(route)).lstrip("/")
        target = (DIST_DIR / clean_path).resolve()

        if not is_relative_to(target, DIST_DIR.resolve()):
            self.send_json({"error": "Static path escapes root"}, HTTPStatus.FORBIDDEN)
            return

        if not target.exists() or not target.is_file():
            target = DIST_DIR / "index.html"

        if not target.exists():
            self.send_json(
                {"error": "Review browser is not built yet", "expectedDist": str(DIST_DIR)},
                HTTPStatus.NOT_FOUND,
            )
            return

        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", mime_for(target))
        self.send_header("Cache-Control", "no-store" if target.name == "index.html" else "public, max-age=31536000")
        self.end_headers()
        with target.open("rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > LIMITS.max_request_bytes:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_exception_json(self, error: Exception) -> None:
        if isinstance(error, FileNotFoundError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(error, PermissionError):
            status = HTTPStatus.FORBIDDEN
        elif isinstance(error, UnicodeError):
            status = HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        elif isinstance(error, ValueError) and str(error).startswith("File is too large"):
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        elif isinstance(error, ValueError):
            status = HTTPStatus.BAD_REQUEST
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self.send_json({"error": str(error)}, status)

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,PUT,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args: Any) -> None:
        return


def bind_with_fallback(host: str, preferred_port: int, handler: type[ReviewHandler]) -> ThreadingHTTPServer:
    attempts = 1 if preferred_port == 0 else 20
    port = preferred_port
    for _ in range(attempts):
        try:
            return ThreadingHTTPServer((host, port), handler)
        except OSError:
            if preferred_port == 0:
                raise
            port += 1
    raise RuntimeError(f"Could not bind a local port starting at {preferred_port}")


def create_server(
    workspace_root: Path,
    host: str,
    port: int,
    codex_host: str,
    codex_host_source: str,
) -> tuple[ThreadingHTTPServer, str, ReviewState]:
    state = ReviewState(workspace_root, codex_host, codex_host_source)
    ReviewHandler.state = state

    server = bind_with_fallback(host, port, ReviewHandler)
    bound_host, bound_port = server.server_address
    base_url = f"http://{bound_host}:{bound_port}"
    ReviewHandler.base_url = base_url
    write_registry_files(state, base_url)
    return server, base_url, state
