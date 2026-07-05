from __future__ import annotations

import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import LIMITS
from .scan import classify_path, language_for, should_skip_file
from .utils import hash_file, normalize_relative


@dataclass(frozen=True)
class TextFileSaveRequest:
    relative_path: str
    content: str
    base_content_hash: str


PathResolver = Callable[[str], Path]


def text_file_status(resolve_path: PathResolver, relative_path: str) -> dict[str, Any]:
    absolute_path = resolve_path(relative_path)
    return text_file_metadata(relative_path, absolute_path, include_hash=True)


def save_text_file(resolve_path: PathResolver, file_lock: threading.Lock, payload: Any) -> dict[str, Any]:
    request = parse_save_payload(payload)
    encoded = request.content.encode("utf-8")
    if len(encoded) > LIMITS.max_text_bytes:
        raise ValueError("File is too large for text editing")

    absolute_path = resolve_path(request.relative_path)
    with file_lock:
        current = text_file_metadata(request.relative_path, absolute_path, include_hash=True)
        if current["contentHash"] != request.base_content_hash:
            return {
                "saved": False,
                "conflict": True,
                "file": current,
            }

        write_text_file_atomically(absolute_path, encoded)
        file_info = text_file_metadata(request.relative_path, absolute_path, include_hash=True)
        return {
            "saved": True,
            "conflict": False,
            "file": file_info,
        }


def parse_save_payload(payload: Any) -> TextFileSaveRequest:
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object")

    relative_path = normalize_relative(payload.get("path"))
    content = payload.get("content")
    base_content_hash = payload.get("baseContentHash")
    if not relative_path:
        raise ValueError("Missing or invalid path")
    if not isinstance(content, str):
        raise ValueError("Expected string content")
    if not isinstance(base_content_hash, str) or not base_content_hash:
        raise ValueError("Expected baseContentHash")
    return TextFileSaveRequest(
        relative_path=relative_path,
        content=content,
        base_content_hash=base_content_hash,
    )


def text_file_metadata(relative_path: str, absolute_path: Path, include_hash: bool = False) -> dict[str, Any]:
    if should_skip_file(absolute_path.name, relative_path):
        raise PermissionError("File is not editable")
    if not absolute_path.exists() or not absolute_path.is_file():
        raise FileNotFoundError("File not found")

    stat_result = absolute_path.stat()
    if stat_result.st_size > LIMITS.max_text_bytes:
        raise ValueError("File is too large for text editing")
    kind = classify_path(absolute_path.name, stat_result.st_size)
    if kind != "text":
        raise ValueError("File is not a supported text file")

    file_info: dict[str, Any] = {
        "relativePath": relative_path,
        "absolutePath": str(absolute_path),
        "kind": "text",
        "language": language_for(relative_path),
        "size": stat_result.st_size,
        "mtimeMs": stat_result.st_mtime * 1000,
    }
    if include_hash:
        file_info["contentHash"] = hash_file(absolute_path)
    return file_info


def write_text_file_atomically(absolute_path: Path, encoded: bytes) -> None:
    existing_mode = stat.S_IMODE(absolute_path.stat().st_mode)
    temp_handle = tempfile.NamedTemporaryFile(
        "wb",
        delete=False,
        dir=absolute_path.parent,
        prefix=f".{absolute_path.name}.",
        suffix=".codex-ux-tmp",
    )
    temp_path = Path(temp_handle.name)
    try:
        with temp_handle as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temp_path, existing_mode)
        os.replace(temp_path, absolute_path)
        sync_parent_directory(absolute_path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def sync_parent_directory(parent: Path) -> None:
    try:
        directory_fd = os.open(parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        return
    finally:
        os.close(directory_fd)
