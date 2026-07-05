from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
SERVER_ROOT = SCRIPT_PATH.parent.parent
APP_ROOT = SERVER_ROOT.parent
DIST_CANDIDATES = [
    APP_ROOT / "web" / "dist",
    APP_ROOT / "assets" / "file-browser" / "dist",
]
DIST_DIR = next((path for path in DIST_CANDIDATES if path.exists()), DIST_CANDIDATES[0])
REGISTRY_DIR = Path.home() / ".codex-ux" / "file-browser"
WORKSPACE_REGISTRY_DIR = REGISTRY_DIR / "workspaces"
WORKSPACE_LOCK_DIR = REGISTRY_DIR / "locks"


@dataclass(frozen=True)
class Limits:
    max_files: int = 8000
    max_text_bytes: int = 2 * 1024 * 1024
    max_image_bytes: int = 20 * 1024 * 1024
    max_pdf_bytes: int = 30 * 1024 * 1024
    max_request_bytes: int = 6 * 1024 * 1024
    max_intents: int = 1000
    max_intent_body_chars: int = 10000
    max_search_seconds: float = 6.0
    max_search_matches_per_file: int = 3


LIMITS = Limits()

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".vercel",
    ".netlify",
    ".cache",
    "node_modules",
    "bower_components",
    "dist",
    "build",
    "out",
    "coverage",
    "target",
    "vendor",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

ALLOWED_DOT_DIRS = {".github", ".vscode"}

IGNORED_FILES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "Cargo.lock",
    ".DS_Store",
}

SECRET_FILE_NAMES = {
    ".npmrc",
    ".pypirc",
    ".netrc",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

PDF_EXTENSIONS = {".pdf"}

TEXT_EXTENSIONS = {
    "",
    ".astro",
    ".bash",
    ".c",
    ".cc",
    ".cjs",
    ".cfg",
    ".cmake",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".go",
    ".graphql",
    ".h",
    ".hpp",
    ".html",
    ".htm",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".json5",
    ".jsonc",
    ".jsx",
    ".kt",
    ".less",
    ".lua",
    ".m",
    ".md",
    ".mdx",
    ".mk",
    ".mjs",
    ".mts",
    ".cts",
    ".php",
    ".pl",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".toml",
    ".tsx",
    ".ts",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
    ".zsh",
}

LANGUAGE_BY_EXT = {
    ".astro": "html",
    ".c": "cpp",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".css": "css",
    ".cjs": "javascript",
    ".cmake": "cmake",
    ".cts": "typescript",
    ".go": "go",
    ".html": "html",
    ".htm": "html",
    ".ini": "properties",
    ".js": "javascript",
    ".json": "json",
    ".json5": "json",
    ".jsonc": "json",
    ".jsx": "javascript",
    ".md": "markdown",
    ".mdx": "markdown",
    ".mk": "makefile",
    ".mjs": "javascript",
    ".mts": "typescript",
    ".properties": "properties",
    ".py": "python",
    ".rs": "rust",
    ".scss": "css",
    ".sh": "shell",
    ".sql": "sql",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "html",
    ".xml": "html",
    ".yaml": "yaml",
    ".yml": "yaml",
}
