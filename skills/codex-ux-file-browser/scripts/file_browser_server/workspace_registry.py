from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import WORKSPACE_REGISTRY_DIR
from .protocol import APP_NAME, SCHEMA_WORKSPACE_BROWSER, workspace_key
from .utils import utc_now

if TYPE_CHECKING:
    from .state import ReviewState


def workspace_registry_path(workspace_root: Path) -> Path:
    return WORKSPACE_REGISTRY_DIR / f"{workspace_key(workspace_root.resolve())}.json"


def build_registry_payload(
    state: ReviewState,
    base_url: str,
    handoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry_path = workspace_registry_path(state.workspace_root)
    payload = {
        "schemaVersion": SCHEMA_WORKSPACE_BROWSER,
        "app": APP_NAME,
        "workspaceKey": workspace_key(state.workspace_root),
        "workspaceRoot": str(state.workspace_root),
        "sessionId": state.session.get("sessionId"),
        "sessionPath": str(state.session_path),
        "snapshotUrl": f"{base_url}/snapshot.json",
        "url": base_url,
        "registryPath": str(registry_path),
        "pid": os.getpid(),
        "updatedAt": utc_now(),
    }
    if handoff:
        payload["handoff"] = handoff
    return payload


def write_registry_files(state: ReviewState, base_url: str, handoff: dict[str, Any] | None = None) -> None:
    payload = build_registry_payload(state, base_url, handoff)
    registry_path = workspace_registry_path(state.workspace_root)

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload, indent=2) + "\n", "utf-8")
