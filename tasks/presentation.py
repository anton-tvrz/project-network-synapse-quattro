"""Presentation tasks — self-service portal management (ADR-0005, Issue #188)."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from invoke import task

if TYPE_CHECKING:
    from invoke.context import Context

from .shared import execute_command


@task(
    help={
        "host": "Interface to bind (default 127.0.0.1).",
        "port": "Port to listen on (default 8081 — 8080 is the Temporal UI).",
    }
)
def start(ctx: Context, host: str = "127.0.0.1", port: int = 8081) -> None:
    """Start the self-service presentation portal.

    Requires PRESENTATION_API_KEYS in the environment; without it every
    request is rejected with 401. See .env.example for the key format.
    """
    print(f"Starting presentation portal on http://{host}:{port} ...")
    execute_command(
        ctx,
        f"PRESENTATION_HOST={shlex.quote(host)} PRESENTATION_PORT={port} python -m synapse_presentation.main",
    )
