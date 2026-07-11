"""Temporal activities for backing up device configurations."""

from __future__ import annotations

from temporalio import activity

from synapse_workers.activities._gnmi_io import fetch_config_via_gnmi


@activity.defn
async def backup_running_config(device_hostname: str, ip_address: str) -> str:
    """Backup the current running configuration from a device via gNMI GET.

    Returns config as JSON string. Credentials are resolved from the worker's
    environment inside the gNMI helper — never accepted as arguments, which
    Temporal would persist in workflow history (Issue #166).
    """
    activity.logger.info(f"Backing up config for {device_hostname} at {ip_address}")
    return await fetch_config_via_gnmi(device_hostname, ip_address)


@activity.defn
async def store_backup(device_hostname: str, config: str) -> None:
    """Store a configuration backup.

    For the MVP, we just log it. A real system would write to S3 or git.
    """
    activity.logger.info(f"Stored backup for {device_hostname} ({len(config)} bytes)")
    # TODO: Implement actual persistent storage write
