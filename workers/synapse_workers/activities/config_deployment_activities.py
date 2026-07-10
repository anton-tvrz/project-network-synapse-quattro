"""Temporal activities for deploying configurations to network devices."""

from __future__ import annotations

import time

from temporalio import activity

from synapse_workers.activities._gnmi_io import deploy_config_via_gnmi
from synapse_workers.metrics import intent_connectivity_total, intent_provisioning_duration_seconds

# TODO: Add device credential management (env vars or vault)
# For MVP, we will use Containerlab default SR Linux credentials
DEFAULT_USER = "admin"
DEFAULT_PASS = "NokiaSrl1!"  # noqa: S105


@activity.defn
async def deploy_config(device_hostname: str, ip_address: str, config_json: str) -> bool:
    """Deploy configuration to a network device via gNMI."""
    activity.logger.info(f"Deploying config to {device_hostname} at {ip_address}")

    started = time.monotonic()
    result = await deploy_config_via_gnmi(
        device_hostname=device_hostname,
        ip_address=ip_address,
        config_payload=config_json,
        username=DEFAULT_USER,
        password=DEFAULT_PASS,
    )

    if not result:
        intent_connectivity_total.labels(status="failed").inc()
        raise RuntimeError(f"Config deployment failed for {device_hostname}")

    intent_provisioning_duration_seconds.observe(time.monotonic() - started)
    intent_connectivity_total.labels(status="deployed").inc()
    return True


@activity.defn
async def rollback_config(device_hostname: str, ip_address: str, backup_config_json: str) -> bool:
    """Rollback device to previous configuration via gNMI SET."""
    activity.logger.info(f"Rolling back config for {device_hostname} to previous state")

    result = await deploy_config_via_gnmi(
        device_hostname=device_hostname,
        ip_address=ip_address,
        config_payload=backup_config_json,
        username=DEFAULT_USER,
        password=DEFAULT_PASS,
        # replace, not merge: a merge would keep whatever the failed deploy
        # added instead of returning to the backed-up baseline (Issue #164)
        replace=True,
    )

    if not result:
        intent_connectivity_total.labels(status="rollback_failed").inc()
        raise RuntimeError(f"Rollback failed for {device_hostname}. Device may be in an inconsistent state!")

    intent_connectivity_total.labels(status="rolled_back").inc()
    return True
