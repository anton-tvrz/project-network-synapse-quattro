"""Uvicorn entry point for the presentation service."""

from __future__ import annotations

import os

import uvicorn

from synapse_presentation.app import create_app

app = create_app()


def run() -> None:
    """Serve the presentation app (host/port from environment)."""
    uvicorn.run(
        app,
        host=os.getenv("PRESENTATION_HOST", "127.0.0.1"),
        port=int(os.getenv("PRESENTATION_PORT", "8080")),
    )


if __name__ == "__main__":
    run()
