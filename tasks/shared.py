"""Shared utilities for invoke tasks."""

from __future__ import annotations

from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

BACKEND_DIR = PROJECT_ROOT / "backend"
WORKERS_DIR = PROJECT_ROOT / "workers"
TESTS_DIR = PROJECT_ROOT / "tests"
DOCS_DIR = PROJECT_ROOT / "docs"


def execute_command(ctx, command: str, pty: bool = True, warn: bool = False, **kwargs):
    """Execute a command with consistent settings."""
    return ctx.run(command, pty=pty, warn=warn, **kwargs)
