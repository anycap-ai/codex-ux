from __future__ import annotations

import hashlib
import mimetypes
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def normalize_relative(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("\\", "/").lstrip("/")
    parts = normalized.split("/")
    if "\x00" in normalized or any(part in ("", "..") for part in parts):
        return None
    return normalized


def require_path(query: dict[str, list[str]]) -> str:
    relative_path = normalize_relative(first(query, "path"))
    if not relative_path:
        raise ValueError("Missing or invalid path query parameter")
    return relative_path


def first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    return values[0] if values else ""


def clamp_int(value: str, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return fallback
    return max(minimum, min(maximum, parsed))


def image_mime(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    if ext == ".svg":
        return "image/svg+xml"
    return None


def mime_for(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    if guessed:
        return guessed
    if path.suffix == ".js":
        return "text/javascript"
    return "application/octet-stream"


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def hash_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def make_id() -> str:
    raw = f"{time.time_ns()}:{os.getpid()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=0.5)
