from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


CLT_DEVELOPER_DIR = Path("/Library/Developer/CommandLineTools")
CLT_SWIFT = CLT_DEVELOPER_DIR / "usr/bin/swift"


@dataclass(frozen=True)
class SwiftRuntime:
    command: str
    env: dict[str, str]


def find_swift_runtime(base_env: dict[str, str] | None = None) -> SwiftRuntime | None:
    env = dict(os.environ if base_env is None else base_env)
    if platform.system() == "Darwin" and CLT_SWIFT.is_file() and os.access(CLT_SWIFT, os.X_OK):
        env["DEVELOPER_DIR"] = str(CLT_DEVELOPER_DIR)
        return SwiftRuntime(str(CLT_SWIFT), env)

    swift = shutil.which("swift")
    if not swift:
        return None
    return SwiftRuntime(swift, env)
