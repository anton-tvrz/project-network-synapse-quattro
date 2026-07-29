"""Shared utilities for invoke tasks."""

from __future__ import annotations

import os
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

BACKEND_DIR = PROJECT_ROOT / "backend"
WORKERS_DIR = PROJECT_ROOT / "workers"
TESTS_DIR = PROJECT_ROOT / "tests"
DOCS_DIR = PROJECT_ROOT / "docs"

ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load ``path`` into the environment without clobbering existing values.

    Nothing did this before (Issue #189), so every task ran on whatever the
    caller happened to have exported — and `backend.load-schemas` failed on a
    clean shell even with a correctly populated .env sitting in the repo root.

    The caller's environment wins, so ``FOO=x uv run invoke ...`` still
    overrides the file. A missing file is fine: a fresh clone has none, and
    most tasks don't need one.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def execute_command(ctx, command: str, pty: bool = True, warn: bool = False, **kwargs):
    """Execute a command with consistent settings."""
    return ctx.run(command, pty=pty, warn=warn, **kwargs)
