from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import subprocess


CODEX_HOST_APP = "codex-app"
CODEX_HOST_CLI = "codex-cli"
CODEX_HOST_SOURCE_DEFAULT = "default"
CODEX_HOST_SOURCE_PROCESS_TREE = "process-tree"


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    command: str


@dataclass(frozen=True)
class CodexHostDetection:
    host: str
    source: str


ProcessReader = Callable[[int], ProcessInfo | None]


def detect_codex_host(
    start_pid: int | None = None,
    process_reader: ProcessReader | None = None,
) -> CodexHostDetection:
    reader = process_reader or read_process
    for process in iter_process_chain(start_pid, reader):
        host = classify_process(process.command)
        if host:
            return CodexHostDetection(host, CODEX_HOST_SOURCE_PROCESS_TREE)
    return CodexHostDetection(CODEX_HOST_CLI, CODEX_HOST_SOURCE_DEFAULT)


def iter_process_chain(start_pid: int | None, process_reader: ProcessReader) -> Iterator[ProcessInfo]:
    current_pid = start_pid if start_pid is not None else os.getppid()
    seen: set[int] = set()
    while current_pid > 1 and current_pid not in seen:
        seen.add(current_pid)
        process = process_reader(current_pid)
        if process is None:
            return
        yield process
        current_pid = process.ppid


def read_process(pid: int) -> ProcessInfo | None:
    if pid <= 0:
        return None
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "ppid=", "-o", "args="],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
            check=False,
        )
    except Exception:
        return None

    if completed.returncode != 0:
        return None
    line = completed.stdout.strip()
    if not line:
        return None
    parts = line.split(None, 1)
    if not parts:
        return None
    try:
        parent_pid = int(parts[0])
    except ValueError:
        return None
    return ProcessInfo(pid=pid, ppid=parent_pid, command=parts[1] if len(parts) > 1 else "")


def classify_process(command: str) -> str | None:
    command = command.strip()
    if not command:
        return None
    if is_codex_app_process(command):
        return CODEX_HOST_APP
    if is_codex_cli_process(command):
        return CODEX_HOST_CLI
    return None


def is_codex_app_process(command: str) -> bool:
    lower_command = command.lower()
    if "codex.app/" in lower_command or lower_command.endswith("codex.app"):
        return True
    executable = first_command_token(command)
    return executable in {"Codex", "Codex Helper"}


def is_codex_cli_process(command: str) -> bool:
    lower_command = command.lower()
    if "codex-cli" in lower_command:
        return True
    for token in split_command(command)[:4]:
        if Path(token).name.lower() in {"codex", "codex-cli"}:
            return True
    return False


def first_command_token(command: str) -> str:
    tokens = split_command(command)
    if not tokens:
        return ""
    return Path(tokens[0]).name


def split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()
