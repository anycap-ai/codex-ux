from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import (
    ALLOWED_DOT_DIRS,
    IGNORED_DIRS,
    IGNORED_FILES,
    IMAGE_EXTENSIONS,
    LANGUAGE_BY_EXT,
    LIMITS,
    PDF_EXTENSIONS,
    SECRET_FILE_NAMES,
    TEXT_EXTENSIONS,
)


def scan_dir(root: Path, directory: Path, files: list[dict[str, Any]]) -> None:
    if len(files) >= LIMITS.max_files:
        return

    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name.lower())
    except OSError:
        return

    for entry in entries:
        if len(files) >= LIMITS.max_files:
            return
        relative_path = entry.relative_to(root).as_posix()
        if entry.is_dir():
            if not should_skip_dir(entry.name, relative_path):
                scan_dir(root, entry, files)
            continue

        if not entry.is_file() or should_skip_file(entry.name, relative_path):
            continue

        try:
            stat_result = entry.stat()
        except OSError:
            continue

        kind = classify_path(entry.name, stat_result.st_size)
        if not kind:
            continue

        files.append(
            {
                "relativePath": relative_path,
                "absolutePath": str(entry.resolve()),
                "kind": kind,
                "language": language_for(relative_path) if kind == "text" else None,
                "size": stat_result.st_size,
                "mtimeMs": stat_result.st_mtime * 1000,
            }
        )


def should_skip_dir(name: str, relative_path: str) -> bool:
    if name in IGNORED_DIRS:
        return True
    if name.startswith(".") and name not in ALLOWED_DOT_DIRS:
        return True
    parts = {part.lower() for part in relative_path.split("/")}
    return bool(parts.intersection({"tmp", "temp", "cache", "log", "logs"}))


def should_skip_file(name: str, relative_path: str) -> bool:
    lower_name = name.lower()
    lower_path = relative_path.lower()
    if name in IGNORED_FILES or lower_name in SECRET_FILE_NAMES:
        return True
    if lower_name.startswith(".env"):
        return True
    if lower_name.startswith("id_") and lower_name in {"id_rsa", "id_ed25519", "id_dsa", "id_ecdsa"}:
        return True
    if any(lower_name.endswith(ext) for ext in (".pem", ".key", ".p12", ".pfx", ".crt", ".cer")):
        return True
    return any(part in {"credentials", "credential", "secrets", "secret"} for part in lower_path.split("/"))


def classify_path(file_name: str, size: int) -> str | None:
    ext = Path(file_name).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image" if size <= LIMITS.max_image_bytes else None
    if ext in PDF_EXTENSIONS:
        return "pdf" if size <= LIMITS.max_pdf_bytes else None
    if ext in TEXT_EXTENSIONS:
        return "text" if size <= LIMITS.max_text_bytes else None
    return None


def language_for(relative_path: str) -> str:
    name = Path(relative_path).name
    lower_name = name.lower()
    if lower_name in {"makefile", "gnumakefile"}:
        return "makefile"
    if lower_name in {"dockerfile", "containerfile"} or lower_name.endswith(".dockerfile"):
        return "dockerfile"
    if name == "CMakeLists.txt":
        return "cmake"
    return LANGUAGE_BY_EXT.get(Path(relative_path).suffix.lower(), "text")
