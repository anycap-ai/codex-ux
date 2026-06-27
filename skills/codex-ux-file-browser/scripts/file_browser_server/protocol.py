from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from .utils import make_id, normalize_relative, utc_now

APP_NAME = "codex-ux-file-browser"
SCHEMA_SNAPSHOT = "agentux.snapshot.v1"
SCHEMA_SESSION = "agentux.session.v1"
SCHEMA_HANDOFF = "codexux.handoff.v1"
SCHEMA_WORKSPACE_BROWSER = "codexux.workspace-file-browser.v1"
SCHEMA_STARTUP = "codexux.file-browser.startup.v1"
INTENT_PURPOSE = "general-agent-context"
DEFAULT_INTENT_BODY = "mark"

INTENT_HANDLING_GUIDANCE = [
    "Read the provided AgentUX snapshot and inspect its intents array before responding; do not answer from the handoff prompt alone.",
    "Each intent is user-authored context anchored to a target in the shared surface.",
    "Handle open intents only; resolved intents are already done and do not need a response.",
    "Unless the user explicitly asks about resolved intents, do not mention, summarize, or list them in the final reply.",
    "Triage intent body before reading files; if the snapshot has enough context to answer, respond without extra file reads.",
    "Group intents by file and batch file reads; do not alternate one intent with one tool call when several intents can be handled together.",
    "Use anchors as fast locators. For text anchors, start from line/column and nearby text; do not recompute anchorHash during normal intent handling.",
    "A File Browser intent is shown to the user as a note. It can be a question, observation, instruction, warning, approval, context, quick marker, or edit request.",
    "When an intent body is exactly \"mark\", treat it as a lightweight location marker and use the user's current request or thread context to decide what to do with that location.",
    "Do not assume every open intent requires a file change.",
    "Respond to each open intent in the way it asks for: answer questions, use context, explain tradeoffs, or edit files only when requested or clearly implied.",
    "Infer the response language from each intent body, and reply in the user's language for that intent.",
    "Also consider the user's earlier messages in the Codex thread when interpreting intents and deciding how to respond.",
]

FINAL_REPLY_GUIDANCE = [
    "Make the final reply easy for the user to read and map back to their notes in the File Browser.",
    "When there are multiple open intents, clearly distinguish which response belongs to which intent, usually with short Markdown headers or compact labels that include the file/location and a brief paraphrase.",
    "Do not repeat the full intent body unless it is necessary.",
    "Choose the most user-friendly structure for the situation: keep simple intents terse, group closely related intents when that is clearer, and avoid rigid status-table formatting unless it genuinely helps.",
    "Put any overall summary after the note-specific responses.",
]


def build_agent_guidance(resolve_url: str = "/api/intents/resolve") -> list[str]:
    return [
        *INTENT_HANDLING_GUIDANCE,
        f"When open intents are fully handled, resolve their ids in one POST when possible by POSTing {{\"ids\":[\"intent_id\"]}} to {resolve_url}.",
        "Only resolve intents you actually handled; leave unclear, unsafe, or still-pending intents open and report why.",
        *FINAL_REPLY_GUIDANCE,
    ]


AGENT_GUIDANCE = build_agent_guidance()


def empty_session(workspace_root: Path) -> dict[str, Any]:
    session_id = workspace_key(workspace_root)[:12]
    return {
        "schemaVersion": SCHEMA_SESSION,
        "sessionId": f"session_{session_id}",
        "workspaceRoot": str(workspace_root),
        "intents": [],
        "updatedAt": utc_now(),
    }


def workspace_key(workspace_root: Path) -> str:
    return hashlib.sha256(str(workspace_root).encode("utf-8")).hexdigest()[:16]


def sanitize_session(payload: Any, workspace_root: Path, max_intents: int, max_intent_body_chars: int) -> dict[str, Any]:
    session = empty_session(workspace_root)
    intents = payload.get("intents", []) if isinstance(payload, dict) else []
    if not isinstance(intents, list):
        intents = []

    clean_intents = []
    for raw_intent in intents[:max_intents]:
        intent = sanitize_intent(raw_intent, workspace_root, max_intent_body_chars)
        if intent is not None:
            clean_intents.append(intent)

    session["intents"] = clean_intents
    session["updatedAt"] = utc_now()
    return session


def sanitize_intent(raw: Any, workspace_root: Path, max_intent_body_chars: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    raw_body = raw.get("body")
    if not isinstance(raw_body, str):
        return None
    body = raw_body[:max_intent_body_chars].strip() or DEFAULT_INTENT_BODY
    target = sanitize_target(raw.get("target"), workspace_root)
    if target is None:
        return None

    created_at = non_empty_string(raw.get("createdAt")) or utc_now()
    updated_at = non_empty_string(raw.get("updatedAt")) or created_at
    intent_id = non_empty_string(raw.get("id")) or f"intent_{make_id()}"
    status = "resolved" if raw.get("status") == "resolved" else "open"

    return {
        "id": intent_id,
        "kind": "intent",
        "purpose": "note",
        "target": target,
        "body": body,
        "status": status,
        "createdAt": created_at,
        "updatedAt": updated_at,
    }


def sanitize_target(raw: Any, workspace_root: Path) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    locator = raw.get("locator")
    if not isinstance(locator, dict) or locator.get("type") != "workspace-path":
        return None
    file_path = normalize_relative(locator.get("path"))
    anchor = sanitize_anchor(raw.get("anchor"))
    if not file_path or anchor is None:
        return None
    return {
        "kind": "file",
        "locator": {
            "type": "workspace-path",
            "path": file_path,
            "absolutePath": str(workspace_root / file_path),
        },
        "anchor": anchor,
    }


def intent_file_path(intent: dict[str, Any]) -> str | None:
    locator = intent.get("target", {}).get("locator", {})
    path = locator.get("path") if isinstance(locator, dict) else None
    return path if isinstance(path, str) and path else None


def build_surface(workspace_root: Path) -> dict[str, Any]:
    return {
        "id": APP_NAME,
        "kind": "workspace-review",
        "title": "File Browser",
        "workspaceRoot": str(workspace_root),
        "capabilities": {
            "view": False,
            "layer": False,
            "events": False,
            "hostActions": [],
        },
    }


def sanitize_anchor(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    anchor_type = raw.get("type")
    if anchor_type == "text-range":
        return sanitize_text_range_anchor(raw)
    if anchor_type == "image-rect":
        return sanitize_image_rect_anchor(raw)
    if anchor_type == "image-point":
        return sanitize_image_point_anchor(raw)
    if anchor_type == "image-path":
        return sanitize_image_path_anchor(raw)
    if anchor_type == "html-text":
        return sanitize_html_text_anchor(raw)
    if anchor_type == "html-rect":
        return sanitize_html_rect_anchor(raw)
    if anchor_type == "csv-range":
        return sanitize_csv_range_anchor(raw)
    if anchor_type == "pdf-rect":
        return sanitize_pdf_rect_anchor(raw)
    return None


def sanitize_text_range_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    start_line = positive_int(raw.get("startLine"))
    end_line = positive_int(raw.get("endLine"))
    start_column = positive_int(raw.get("startColumn"))
    end_column = positive_int(raw.get("endColumn"))
    selected_text = non_empty_string(raw.get("selectedText"))
    anchor_hash = non_empty_string(raw.get("anchorHash"))
    if not all([start_line, end_line, start_column, end_column, selected_text, anchor_hash]):
        return None
    if end_line < start_line:
        return None
    return {
        "type": "text-range",
        "startLine": start_line,
        "endLine": end_line,
        "startColumn": start_column,
        "endColumn": end_column,
        "selectedText": selected_text,
        "contextBefore": string_value(raw.get("contextBefore")),
        "contextAfter": string_value(raw.get("contextAfter")),
        "anchorHash": anchor_hash,
    }


def sanitize_image_rect_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    image_width = positive_number(raw.get("imageWidth"))
    image_height = positive_number(raw.get("imageHeight"))
    x = finite_number(raw.get("x"))
    y = finite_number(raw.get("y"))
    width = positive_number(raw.get("width"))
    height = positive_number(raw.get("height"))
    if None in (image_width, image_height, x, y, width, height):
        return None
    return {
        "type": "image-rect",
        "imageWidth": image_width,
        "imageHeight": image_height,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def sanitize_image_point_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    image_width = positive_number(raw.get("imageWidth"))
    image_height = positive_number(raw.get("imageHeight"))
    x = finite_number(raw.get("x"))
    y = finite_number(raw.get("y"))
    if None in (image_width, image_height, x, y):
        return None
    return {
        "type": "image-point",
        "imageWidth": image_width,
        "imageHeight": image_height,
        "x": x,
        "y": y,
    }


def sanitize_image_path_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    image_width = positive_number(raw.get("imageWidth"))
    image_height = positive_number(raw.get("imageHeight"))
    points = point_list(raw.get("points"))
    if image_width is None or image_height is None or not points:
        return None
    return {
        "type": "image-path",
        "imageWidth": image_width,
        "imageHeight": image_height,
        "points": points,
    }


def sanitize_html_text_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    document_width = positive_number(raw.get("documentWidth"))
    document_height = positive_number(raw.get("documentHeight"))
    selected_text = non_empty_string(raw.get("selectedText"))
    start_path = int_list(raw.get("startPath"))
    end_path = int_list(raw.get("endPath"))
    start_offset = non_negative_int(raw.get("startOffset"))
    end_offset = non_negative_int(raw.get("endOffset"))
    rects = rect_list(raw.get("rects"))
    if (
        None in (document_width, document_height, start_offset, end_offset)
        or not selected_text
        or start_path is None
        or end_path is None
        or not rects
    ):
        return None
    return {
        "type": "html-text",
        "documentWidth": document_width,
        "documentHeight": document_height,
        "selectedText": selected_text,
        "contextBefore": string_value(raw.get("contextBefore")),
        "contextAfter": string_value(raw.get("contextAfter")),
        "startPath": start_path,
        "endPath": end_path,
        "startOffset": start_offset,
        "endOffset": end_offset,
        "rects": rects,
    }


def sanitize_html_rect_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    document_width = positive_number(raw.get("documentWidth"))
    document_height = positive_number(raw.get("documentHeight"))
    x = finite_number(raw.get("x"))
    y = finite_number(raw.get("y"))
    width = positive_number(raw.get("width"))
    height = positive_number(raw.get("height"))
    if None in (document_width, document_height, x, y, width, height):
        return None
    return {
        "type": "html-rect",
        "documentWidth": document_width,
        "documentHeight": document_height,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def sanitize_csv_range_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    start_row = positive_int(raw.get("startRow"))
    end_row = positive_int(raw.get("endRow"))
    start_column = positive_int(raw.get("startColumn"))
    end_column = positive_int(raw.get("endColumn"))
    row_count = positive_int(raw.get("rowCount"))
    column_count = positive_int(raw.get("columnCount"))
    column_headers = string_list(raw.get("columnHeaders"))
    cell_values = table_values(raw.get("cellValues"))
    selected_text = string_value(raw.get("selectedText"))
    if None in (start_row, end_row, start_column, end_column, row_count, column_count):
        return None
    if end_row < start_row or end_column < start_column:
        return None
    return {
        "type": "csv-range",
        "startRow": start_row,
        "endRow": end_row,
        "startColumn": start_column,
        "endColumn": end_column,
        "rowCount": row_count,
        "columnCount": column_count,
        "columnHeaders": column_headers,
        "cellValues": cell_values,
        "selectedText": selected_text,
    }


def sanitize_pdf_rect_anchor(raw: dict[str, Any]) -> dict[str, Any] | None:
    page_number = positive_int(raw.get("pageNumber"))
    page_width = positive_number(raw.get("pageWidth"))
    page_height = positive_number(raw.get("pageHeight"))
    x = finite_number(raw.get("x"))
    y = finite_number(raw.get("y"))
    width = positive_number(raw.get("width"))
    height = positive_number(raw.get("height"))
    if None in (page_number, page_width, page_height, x, y, width, height):
        return None
    return {
        "type": "pdf-rect",
        "pageNumber": page_number,
        "pageWidth": page_width,
        "pageHeight": page_height,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def positive_int(value: Any) -> int | None:
    parsed = int_value(value)
    return parsed if parsed is not None and parsed > 0 else None


def non_negative_int(value: Any) -> int | None:
    parsed = int_value(value)
    return parsed if parsed is not None and parsed >= 0 else None


def int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def positive_number(value: Any) -> float | None:
    parsed = finite_number(value)
    return parsed if parsed is not None and parsed > 0 else None


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def int_list(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None
    result = []
    for item in value:
        parsed = non_negative_int(item)
        if parsed is None:
            return None
        result.append(parsed)
    return result


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def table_values(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    rows = []
    for row in value:
        if not isinstance(row, list):
            return []
        rows.append([str(cell) for cell in row])
    return rows


def point_list(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list):
        return []
    points = []
    for raw_point in value:
        if not isinstance(raw_point, dict):
            return []
        x = finite_number(raw_point.get("x"))
        y = finite_number(raw_point.get("y"))
        if x is None or y is None:
            return []
        points.append({"x": x, "y": y})
    return points


def rect_list(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list):
        return []
    rects = []
    for raw_rect in value:
        if not isinstance(raw_rect, dict):
            return []
        x = finite_number(raw_rect.get("x"))
        y = finite_number(raw_rect.get("y"))
        width = positive_number(raw_rect.get("width"))
        height = positive_number(raw_rect.get("height"))
        if None in (x, y, width, height):
            return []
        rects.append({"x": x, "y": y, "width": width, "height": height})
    return rects
