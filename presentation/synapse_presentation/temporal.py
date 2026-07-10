"""Temporal client dependency for the presentation layer.

Isolated so tests can override it via ``app.dependency_overrides`` with a
mocked client (per ADR-0004 test types: unit tests mock the Temporal client).
"""

from __future__ import annotations

import os

from temporalio.client import Client

TASK_QUEUE = "network-changes"

_client: Client | None = None


async def get_temporal_client() -> Client:
    """Lazily connect to Temporal and reuse the client across requests."""
    global _client  # noqa: PLW0603 — deliberate process-wide client reuse
    if _client is None:
        _client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "localhost:7233"))
    return _client
