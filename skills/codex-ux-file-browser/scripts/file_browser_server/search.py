from __future__ import annotations

import json
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import LIMITS
from .scan import should_skip_file
from .utils import is_relative_to, terminate_process

if TYPE_CHECKING:
    from .state import ReviewState


def search_workspace(state: ReviewState, query: str, limit: int) -> list[dict[str, Any]]:
    rg_results = search_with_rg(state, query, limit)
    if rg_results is not None:
        return rg_results
    return search_with_python(state, query, limit)


def search_with_rg(state: ReviewState, query: str, limit: int) -> list[dict[str, Any]] | None:
    if not shutil.which("rg"):
        return None

    args = [
        "rg",
        "--json",
        "--fixed-strings",
        "--line-number",
        "--column",
        "--max-count",
        str(LIMITS.max_search_matches_per_file),
        "--max-filesize",
        f"{LIMITS.max_text_bytes // 1024}K",
        "--no-messages",
        "--color",
        "never",
        "--glob",
        "!**/.git/**",
        "--glob",
        "!**/node_modules/**",
        "--glob",
        "!**/dist/**",
        "--glob",
        "!**/build/**",
        "--glob",
        "!**/.next/**",
        "--glob",
        "!**/coverage/**",
        query,
        str(state.workspace_root),
    ]

    process: subprocess.Popen[str] | None = None
    selector: selectors.BaseSelector | None = None
    results: list[dict[str, Any]] = []
    try:
        process = subprocess.Popen(
            args,
            cwd=state.workspace_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return None

    if process.stdout is None:
        terminate_process(process)
        return None

    try:
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + LIMITS.max_search_seconds

        while True:
            if len(results) >= limit:
                terminate_process(process)
                return results

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_process(process)
                return results

            events = selector.select(timeout=min(0.2, remaining))
            if not events:
                if process.poll() is not None:
                    break
                continue

            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue

            result = parse_rg_match(line, state)
            if result is not None:
                results.append(result)

        return_code = process.wait(timeout=0.2)
        return results if return_code in (0, 1) else None
    except Exception:
        terminate_process(process)
        return None
    finally:
        if selector is not None:
            selector.close()


def parse_rg_match(line: str, state: ReviewState) -> dict[str, Any] | None:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return None
    if message.get("type") != "match":
        return None

    data = message.get("data", {})
    absolute_path = Path(data.get("path", {}).get("text", "")).resolve()
    if not is_relative_to(absolute_path, state.workspace_root):
        return None

    relative_path = absolute_path.relative_to(state.workspace_root).as_posix()
    if should_skip_file(absolute_path.name, relative_path):
        return None

    submatches = data.get("submatches") or [{}]
    return {
        "relativePath": relative_path,
        "absolutePath": str(absolute_path),
        "line": data.get("line_number", 1),
        "column": int(submatches[0].get("start", 0)) + 1,
        "preview": str(data.get("lines", {}).get("text", "")).rstrip(),
    }


def search_with_python(state: ReviewState, query: str, limit: int) -> list[dict[str, Any]]:
    needle = query.casefold()
    results = []
    deadline = time.monotonic() + LIMITS.max_search_seconds
    for file in state.get_files():
        if time.monotonic() > deadline:
            break
        if len(results) >= limit:
            break
        if file.get("kind") != "text" or file.get("size", 0) > LIMITS.max_text_bytes:
            continue
        absolute_path = Path(file["absolutePath"])
        try:
            handle = absolute_path.open("r", encoding="utf-8", errors="ignore")
        except Exception:
            continue

        with handle:
            for index, line in enumerate(handle, start=1):
                if time.monotonic() > deadline:
                    return results
                column = line.casefold().find(needle)
                if column >= 0:
                    results.append(
                        {
                            "relativePath": file["relativePath"],
                            "absolutePath": file["absolutePath"],
                            "line": index,
                            "column": column + 1,
                            "preview": line.rstrip(),
                        }
                    )
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
    return results
