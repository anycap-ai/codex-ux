from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .codex_host import CODEX_HOST_CLI
from .workspace_registry import write_registry_files
from .protocol import APP_NAME, SCHEMA_HANDOFF, build_agent_guidance
from .utils import utc_now

if TYPE_CHECKING:
    from .state import ReviewState


def build_handoff_payload(state: ReviewState, base_url: str) -> dict[str, Any]:
    snapshot_url = f"{base_url}/snapshot.json?intents=open"
    prompt = build_handoff_prompt(state, base_url, snapshot_url)
    return {
        "schemaVersion": SCHEMA_HANDOFF,
        "app": APP_NAME,
        "codexHost": getattr(state, "codex_host", CODEX_HOST_CLI),
        "codexHostSource": getattr(state, "codex_host_source", "default"),
        "workspaceRoot": str(state.workspace_root),
        "sessionId": state.session.get("sessionId"),
        "sessionPath": str(state.session_path),
        "snapshotUrl": snapshot_url,
        "url": base_url,
        "prompt": prompt,
        "requestedAt": utc_now(),
    }


def build_handoff_prompt(state: ReviewState, base_url: str, snapshot_url: str) -> str:
    return " ".join(
        [
            "Review Codex UX File Browser notes for the current workspace.",
            f"Workspace: {state.workspace_root}.",
            f"Read the AgentUX snapshot at {snapshot_url}.",
            *build_agent_guidance(f"{base_url}/api/intents/resolve"),
        ]
    )


def write_handoff_files(state: ReviewState, handoff: dict[str, Any]) -> None:
    state.handoff_path.write_text(json.dumps(handoff, indent=2) + "\n", "utf-8")
    write_registry_files(state, handoff["url"], handoff)
