"""SuzieQ drift scoring and Prometheus exporter (Issue #74).

SuzieQ runs its own state assertions (BGP sessions established, interfaces up,
...) against the collected fabric snapshots. This module turns that assert
output into drift metrics and exposes them on a ``/metrics`` endpoint scraped
by Prometheus (job ``suzieq_exporter`` in development/prometheus/prometheus.yml),
complementing the Infrahub-derived ``compliance_posture`` drift written to
InfluxDB.

Metrics:
    suzieq_drift_score{device}     per-device fraction of failing assertions (0..1)
    suzieq_drift_score_aggregate   fleet-wide mean of the per-device scores (0..1)

Run as an exporter (refreshes on an interval, serves until killed):
    uv run invoke collector.suzieq-exporter
or one-shot for inspection:
    uv run python -m network_synapse.collector.suzieq_drift --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from prometheus_client import CollectorRegistry, Gauge, start_http_server

from network_synapse.collector.suzieq_client import SuzieqClient

logger = logging.getLogger(__name__)

# SuzieQ tables whose assert output contributes to the drift score.
ASSERT_TABLES = ("bgp", "interface")

# Status column keys SuzieQ has used across versions; value "fail" == failure.
_STATUS_KEYS = ("assert", "result", "status")

DEFAULT_EXPORTER_PORT = 9275
DEFAULT_REFRESH_SECONDS = 60

REGISTRY = CollectorRegistry()
drift_score_gauge = Gauge(
    "suzieq_drift_score",
    "Fraction of failing SuzieQ assertions per device (0..1)",
    ["device"],
    registry=REGISTRY,
)
drift_score_aggregate_gauge = Gauge(
    "suzieq_drift_score_aggregate",
    "Fleet-wide mean of per-device SuzieQ drift scores (0..1)",
    registry=REGISTRY,
)
last_poll_timestamp_gauge = Gauge(
    "suzieq_last_poll_timestamp_seconds",
    "Unix timestamp of the last successful SuzieQ collection",
    registry=REGISTRY,
)


def row_failed(row: dict) -> bool:
    """True if a SuzieQ assert row reports a failed assertion."""
    for key in _STATUS_KEYS:
        value = row.get(key)
        if value is not None:
            return str(value).lower() == "fail"
    return False


def drift_score_by_device(rows: list[dict]) -> dict[str, float]:
    """Score each device as its fraction of failing assert rows (0..1).

    Rows without a ``hostname`` are ignored (nothing to attribute them to).
    """
    totals: dict[str, int] = {}
    failures: dict[str, int] = {}
    for row in rows:
        hostname = row.get("hostname")
        if not hostname:
            continue
        totals[hostname] = totals.get(hostname, 0) + 1
        if row_failed(row):
            failures[hostname] = failures.get(hostname, 0) + 1
    return {host: failures.get(host, 0) / total for host, total in totals.items()}


def drift_score_aggregate(scores: dict[str, float]) -> float:
    """Fleet-wide mean of per-device scores (0.0 for an empty fleet)."""
    if not scores:
        return 0.0
    return sum(scores.values()) / len(scores)


def collect_drift(client: SuzieqClient) -> dict[str, float]:
    """Fetch every assert table and reduce it to per-device drift scores."""
    rows: list[dict] = []
    for table in ASSERT_TABLES:
        rows.extend(client.assert_table(table))
    return drift_score_by_device(rows)


def update_gauges(scores: dict[str, float]) -> None:
    """Publish per-device and aggregate scores, clearing stale device series.

    Also stamps the poll timestamp — the SuzieQStale alert measures collection
    freshness as ``time() - suzieq_last_poll_timestamp_seconds``, so a stalled
    poller must leave the timestamp behind rather than simply stop updating
    scores that would otherwise look plausibly current.
    """
    drift_score_gauge.clear()
    for device, score in scores.items():
        drift_score_gauge.labels(device=device).set(score)
    drift_score_aggregate_gauge.set(drift_score_aggregate(scores))
    last_poll_timestamp_gauge.set(time.time())


def _refresh() -> dict[str, float]:
    """Pull the current drift scores from SuzieQ and update the gauges."""
    with SuzieqClient.from_env() as client:
        scores = collect_drift(client)
    update_gauges(scores)
    logger.info("suzieq drift: %d devices, aggregate=%.3f", len(scores), drift_score_aggregate(scores))
    return scores


def main(argv: list[str] | None = None) -> int:
    """Serve SuzieQ drift metrics, or print one snapshot with ``--dry-run``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Collect once, print scores, don't serve")
    parser.add_argument("--port", type=int, default=int(os.getenv("SUZIEQ_EXPORTER_PORT", DEFAULT_EXPORTER_PORT)))
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("SUZIEQ_EXPORTER_INTERVAL", DEFAULT_REFRESH_SECONDS)),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        scores = _refresh()
    except Exception as exc:
        logger.error("suzieq drift collection failed: %s", exc)
        return 1

    if args.dry_run:
        for device, score in sorted(scores.items()):
            print(f"{device} {score}")
        print(f"aggregate {drift_score_aggregate(scores)}")
        return 0

    start_http_server(args.port, registry=REGISTRY)
    logger.info("serving suzieq drift metrics on :%d every %ds", args.port, args.interval)
    while True:  # pragma: no cover - long-running serve loop
        time.sleep(args.interval)
        try:
            _refresh()
        except Exception as exc:
            logger.error("suzieq drift refresh failed: %s", exc)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
