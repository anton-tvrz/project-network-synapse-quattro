"""Collector tasks — SuzieQ drift exporter (Issue #74)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from invoke import task

if TYPE_CHECKING:
    from invoke.context import Context

from .shared import execute_command


@task(
    help={
        "dry-run": "Collect one snapshot, print per-device drift scores, and exit.",
        "port": "Port to expose the /metrics endpoint on (default 9275).",
        "interval": "Seconds between SuzieQ refreshes (default 60).",
    }
)
def suzieq_exporter(ctx: Context, dry_run: bool = False, port: int = 9275, interval: int = 60) -> None:
    """Export SuzieQ assert-based drift scores to Prometheus (job suzieq_exporter).

    Serves suzieq_drift_score{device} + suzieq_drift_score_aggregate until
    killed; use --dry-run for a one-shot look at the current scores.
    """
    flags = f" --port {port} --interval {interval}"
    if dry_run:
        flags += " --dry-run"
    execute_command(ctx, f"python -m network_synapse.collector.suzieq_drift{flags}")
