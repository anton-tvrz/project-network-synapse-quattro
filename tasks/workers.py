"""Worker tasks — Temporal worker management and testing."""

from __future__ import annotations

from invoke import task

from .shared import execute_command


@task
def start(ctx, address="localhost:7233", queue="network-changes"):
    """Start the Temporal worker."""
    print(f"Starting Temporal worker (address={address}, queue={queue})...")
    execute_command(
        ctx,
        f"TEMPORAL_ADDRESS={address} python -m synapse_workers.worker",
    )


@task
def test(ctx):
    """Run worker-specific tests."""
    execute_command(ctx, "pytest tests/ -v -k 'worker or workflow or activity' --timeout=60")
