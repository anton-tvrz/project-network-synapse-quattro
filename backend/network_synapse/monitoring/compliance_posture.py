"""Hourly compliance posture writer — Infrahub to InfluxDB (Issue #70).

Queries Infrahub for every device, scores how completely each one is
modeled in the source of truth, and writes the results to InfluxDB with
``environment`` and ``device_group`` tags, enabling the
"compliance posture over time" dashboard (Issue #71).

Metrics written (measurement / field):
  - ``compliance_posture`` / ``completeness``: per-device modeling
    completeness (0..1), tagged with ``device`` and ``device_group``.
  - ``compliance_posture`` / ``drift_score``: per-device structural drift
    (0..1), only when a running config was available to compare.
  - ``compliance_posture_fleet`` / ``lineage_coverage_ratio``: fleet-wide
    mean completeness.

NOTE: ``lineage_coverage_ratio`` is currently a *stand-in* derived from
modeling completeness. Once the intent schemas (intent-model skill) are
loaded into Infrahub, replace `compute_device_completeness` with a true
intent-lineage query and keep the metric contract unchanged.

Scheduling (hourly cron):
    0 * * * * cd /path/to/repo && uv run invoke backend.write-posture

Environment variables:
    INFLUXDB_URL     InfluxDB base URL (default http://localhost:8086)
    INFLUXDB_TOKEN   API token (default dev-token, matches docker-compose)
    INFLUXDB_ORG     Organisation (default synapse)
    INFLUXDB_BUCKET  Bucket (default compliance)
    ENVIRONMENT      Environment tag value (default lab)
    INFRAHUB_URL / INFRAHUB_API_TOKEN — see infrahub.client
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from network_synapse.infrahub.client import InfrahubConfigClient

if TYPE_CHECKING:
    from network_synapse.infrahub.models import DeviceConfig

logger = logging.getLogger(__name__)

DEVICE_MEASUREMENT = "compliance_posture"
FLEET_MEASUREMENT = "compliance_posture_fleet"


@dataclass
class DevicePosture:
    """Compliance posture for a single device."""

    device: str
    device_group: str
    completeness: float
    missing: list[str] = field(default_factory=list)
    drift_score: float | None = None


def compute_device_completeness(config: DeviceConfig) -> tuple[float, list[str]]:
    """Score how completely a device is modeled in Infrahub (0..1).

    Six components, one point each: ASN, router-id, management IP, role,
    at least one routed (IP-bearing) interface, and at least one BGP session.
    Returns the ratio plus the names of missing components.
    """
    checks = {
        "asn": config.device.asn > 0,
        "router_id": bool(config.device.router_id),
        "management_ip": bool(config.device.management_ip),
        "role": bool(config.device.role),
        "routed_interface": any(i.ip_address for i in config.interfaces),
        "bgp_sessions": len(config.bgp_sessions) > 0,
    }
    missing = [name for name, ok in checks.items() if not ok]
    return (len(checks) - len(missing)) / len(checks), missing


def compute_drift_score(intended_json: str, running_json: str) -> float:
    """Score structural drift between intended and running config (0..1).

    The score is the fraction of top-level config sections (union of both
    documents) whose content differs. Unparseable input scores 1.0.
    """
    try:
        intended = json.loads(intended_json)
        running = json.loads(running_json)
    except (json.JSONDecodeError, TypeError):
        return 1.0
    if not isinstance(intended, dict) or not isinstance(running, dict):
        return 1.0

    sections = set(intended) | set(running)
    if not sections:
        return 0.0
    _sentinel = object()
    differing = sum(1 for key in sections if intended.get(key, _sentinel) != running.get(key, _sentinel))
    return differing / len(sections)


def fleet_coverage_ratio(postures: list[DevicePosture]) -> float:
    """Mean device completeness across the fleet (0.0 for an empty fleet)."""
    if not postures:
        return 0.0
    return sum(p.completeness for p in postures) / len(postures)


def collect_posture(client: InfrahubConfigClient) -> list[DevicePosture]:
    """Query Infrahub and compute posture for every device."""
    postures: list[DevicePosture] = []
    for hostname in client.list_devices():
        config = client.get_device_config(hostname)
        completeness, missing = compute_device_completeness(config)
        postures.append(
            DevicePosture(
                device=hostname,
                device_group=config.device.role or "unknown",
                completeness=completeness,
                missing=missing,
            )
        )
        if missing:
            logger.warning(f"{hostname}: incomplete modeling, missing {missing}")
    return postures


def _escape_tag(value: str) -> str:
    """Escape a line-protocol tag value (spaces, commas, equals signs)."""
    return value.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def build_influx_lines(postures: list[DevicePosture], environment: str, timestamp_s: int) -> list[str]:
    """Render postures as InfluxDB line protocol (seconds precision)."""
    env_tag = _escape_tag(environment)
    lines = []
    for posture in postures:
        tags = (
            f"environment={env_tag}"
            f",device_group={_escape_tag(posture.device_group)}"
            f",device={_escape_tag(posture.device)}"
        )
        fields = f"completeness={posture.completeness}"
        if posture.drift_score is not None:
            fields += f",drift_score={posture.drift_score}"
        lines.append(f"{DEVICE_MEASUREMENT},{tags} {fields} {timestamp_s}")

    lines.append(
        f"{FLEET_MEASUREMENT},environment={env_tag} "
        f"lineage_coverage_ratio={fleet_coverage_ratio(postures)} {timestamp_s}"
    )
    return lines


def write_posture(lines: list[str], url: str, token: str, org: str, bucket: str) -> None:
    """POST line-protocol points to the InfluxDB v2 write API.

    Raises:
        RuntimeError: On any non-2xx response.
    """
    response = httpx.post(
        f"{url.rstrip('/')}/api/v2/write",
        params={"org": org, "bucket": bucket, "precision": "s"},
        headers={"Authorization": f"Token {token}", "Content-Type": "text/plain; charset=utf-8"},
        content="\n".join(lines),
        timeout=30,
    )
    if response.status_code // 100 != 2:
        raise RuntimeError(f"influx write failed: {response.status_code} {response.text}")
    logger.info(f"Wrote {len(lines)} posture points to {bucket}")


def main(argv: list[str] | None = None) -> int:
    """Collect compliance posture from Infrahub and write it to InfluxDB."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print line protocol instead of writing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        with InfrahubConfigClient() as client:
            postures = collect_posture(client)
        lines = build_influx_lines(
            postures,
            environment=os.getenv("ENVIRONMENT", "lab"),
            timestamp_s=int(time.time()),
        )
        if args.dry_run:
            print("\n".join(lines))
            return 0
        write_posture(
            lines,
            url=os.getenv("INFLUXDB_URL", "http://localhost:8086"),
            token=os.getenv("INFLUXDB_TOKEN", "dev-token"),
            org=os.getenv("INFLUXDB_ORG", "synapse"),
            bucket=os.getenv("INFLUXDB_BUCKET", "compliance"),
        )
    except Exception as exc:
        logger.error(f"posture write failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
