"""Temporal client dependency for the presentation layer.

Isolated so tests can override it via ``app.dependency_overrides`` with a
mocked client (per ADR-0004 test types: unit tests mock the Temporal client).
"""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException
from temporalio.client import Client

from synapse_workers.triggers import TASK_QUEUE

__all__ = ["TASK_QUEUE", "get_temporal_client"]

logger = logging.getLogger("synapse_presentation.temporal")

_client: Client | None = None


async def get_temporal_client() -> Client:
    """Lazily connect to Temporal and reuse the client across requests.

    An unreachable Temporal is an upstream failure, so it surfaces as 502
    (matching workflow-start failures), never a bare 500.
    """
    global _client  # noqa: PLW0603 — deliberate process-wide client reuse
    if _client is None:
        address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
        try:
            _client = await Client.connect(address)
        except Exception as exc:
            logger.error("Failed to connect to Temporal at %s: %s", address, exc)
            raise HTTPException(status_code=502, detail="Cannot connect to Temporal") from exc
    return _client
