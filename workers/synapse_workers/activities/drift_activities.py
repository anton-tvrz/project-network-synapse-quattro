"""Temporal activities for drift detection and audit logging."""

from __future__ import annotations

import json

from pygnmi.client import gNMIclient
from temporalio import activity

from network_synapse.scripts.generate_configs import generate_interface_config


@activity.defn
async def fetch_running_config(
    device_hostname: str,
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
    port: int = 57400,
) -> str:
    """Fetch the current running config from a device via gNMI GET.

    Returns the configuration as a JSON string for diff comparison.
    """
    activity.logger.info(f"Fetching running config from {device_hostname} ({ip_address}:{port})")

    try:
        with gNMIclient(target=(ip_address, port), username=username, password=password, insecure=True) as gc:
            result = gc.get(path=["/"])

            if "notification" in result and len(result["notification"]) > 0:
                for notif in result["notification"]:
                    if "update" in notif and len(notif["update"]) > 0:
                        for update in notif["update"]:
                            if "val" in update:
                                return json.dumps(update["val"])

            raise RuntimeError(f"Unexpected gNMI GET format from {device_hostname}: {result}")

    except Exception as e:
        activity.logger.error(f"Failed to fetch running config from {device_hostname}: {e!s}")
        raise RuntimeError(f"Fetch running config failed: {e!s}") from e


@activity.defn
async def render_intended_config(interface_data: dict) -> str:
    """Render intended SR Linux interface config JSON from Infrahub data.

    Wraps the Jinja2 template rendering in an activity to keep
    non-deterministic I/O (file system access) out of the workflow.
    """
    rendered = generate_interface_config(interface_data)
    # Normalize through JSON parse/dump to ensure canonical form
    return json.dumps(json.loads(rendered))


@activity.defn
async def log_audit_event(event_type: str, device_hostname: str, details: str) -> None:
    """Log a structured audit event.

    For the MVP, this emits a structured log entry. A production system
    would write to an audit database, Infrahub, or an external SIEM.
    """
    activity.logger.info(
        "AUDIT event_type=%s device=%s details=%s",
        event_type,
        device_hostname,
        details,
    )
