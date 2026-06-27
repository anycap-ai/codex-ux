from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import LIMITS
from .protocol import (
    AGENT_GUIDANCE,
    SCHEMA_SNAPSHOT,
    INTENT_PURPOSE,
    build_surface,
    empty_session as build_empty_session,
    intent_file_path,
    sanitize_session as sanitize_session_payload,
    workspace_key,
)
from .scan import classify_path, language_for, scan_dir
from .utils import hash_file, is_relative_to, normalize_relative, utc_now


class ReviewState:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        root_key = workspace_key(self.workspace_root)
        self.session_dir = Path(tempfile.gettempdir()) / "codex-ux-file-browser" / root_key
        self.session_path = self.session_dir / "session.json"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.handoff_path = self.session_dir / "handoff.json"
        self.session = self.load_session()
        self.files_cache: list[dict[str, Any]] | None = None
        self.files_cache_at = 0.0

    def empty_session(self) -> dict[str, Any]:
        return build_empty_session(self.workspace_root)

    def load_session(self) -> dict[str, Any]:
        try:
            return self.sanitize_session(json.loads(self.session_path.read_text("utf-8")))
        except Exception:
            return self.empty_session()

    def save_session(self) -> None:
        self.session_path.write_text(json.dumps(self.session, indent=2) + "\n", "utf-8")

    def resolve_intents(self, ids: list[str]) -> dict[str, Any]:
        requested_ids = {str(intent_id).strip() for intent_id in ids if str(intent_id).strip()}
        if not requested_ids:
            return {"resolvedIds": [], "missingIds": [], "intents": self.session.get("intents", [])}

        resolved_ids = []
        resolved_at = utc_now()
        clean_intents = []
        for intent in self.session.get("intents", []):
            if intent.get("id") in requested_ids:
                intent = {**intent, "status": "resolved", "updatedAt": resolved_at}
                resolved_ids.append(intent["id"])
            clean_intents.append(intent)

        self.session["intents"] = clean_intents
        self.session["updatedAt"] = resolved_at
        self.save_session()

        return {
            "resolvedIds": resolved_ids,
            "missingIds": sorted(requested_ids - set(resolved_ids)),
            "intents": clean_intents,
        }

    def sanitize_session(self, payload: Any) -> dict[str, Any]:
        return sanitize_session_payload(payload, self.workspace_root, LIMITS.max_intents, LIMITS.max_intent_body_chars)

    def safe_resolve(self, relative_path: str) -> Path:
        normalized = normalize_relative(relative_path)
        if not normalized:
            raise ValueError("Invalid file path")

        target = (self.workspace_root / normalized).resolve()
        if not is_relative_to(target, self.workspace_root):
            raise ValueError("File path escapes workspace root")
        return target

    def get_files(self) -> list[dict[str, Any]]:
        now = time.time()
        if self.files_cache is not None and now - self.files_cache_at < 3:
            return self.files_cache

        files: list[dict[str, Any]] = []
        scan_dir(self.workspace_root, self.workspace_root, files)
        files.sort(key=lambda item: item["relativePath"])
        self.files_cache = files
        self.files_cache_at = now
        return files

    def build_snapshot(self, open_only: bool = False) -> dict[str, Any]:
        intents = []
        for intent in self.session.get("intents", []):
            if open_only and intent.get("status") != "open":
                continue
            copied = dict(intent)
            path = intent_file_path(copied)
            if path:
                copied["target"] = {
                    **copied.get("target", {}),
                    "locator": {
                        **copied.get("target", {}).get("locator", {}),
                        "absolutePath": str(self.workspace_root / path),
                    },
                }
            copied["kind"] = "intent"
            intents.append(copied)

        file_paths = sorted({path for intent in intents if (path := intent_file_path(intent))})
        open_intents = [intent for intent in intents if intent.get("status") == "open"]
        files = []
        for file_path in file_paths:
            absolute_path = self.workspace_root / file_path
            try:
                stat_result = absolute_path.stat()
                kind = classify_path(absolute_path.name, stat_result.st_size) or "unknown"
                files.append(
                    {
                        "relativePath": file_path,
                        "absolutePath": str(absolute_path),
                        "kind": kind,
                        "language": language_for(file_path) if kind == "text" else None,
                        "size": stat_result.st_size,
                        "mtimeMs": stat_result.st_mtime * 1000,
                        "contentHash": hash_file(absolute_path),
                    }
                )
            except Exception:
                files.append(
                    {
                        "relativePath": file_path,
                        "absolutePath": str(absolute_path),
                        "kind": "missing",
                        "contentHash": None,
                    }
                )

        return {
            "schemaVersion": SCHEMA_SNAPSHOT,
            "surface": build_surface(self.workspace_root),
            "workspaceRoot": str(self.workspace_root),
            "sessionId": self.session.get("sessionId"),
            "createdAt": utc_now(),
            "intentPurpose": INTENT_PURPOSE,
            "openIntentCount": len(open_intents),
            "viewRevision": 0,
            "currentTarget": None,
            "agentGuidance": AGENT_GUIDANCE,
            "files": files,
            "intents": intents,
        }
