"""Temporal activities for drift detection and audit logging."""

from __future__ import annotations

import json

from temporalio import activity

from network_synapse.scripts.generate_configs import generate_interface_config
from synapse_workers.activities._gnmi_io import fetch_config_via_gnmi


@activity.defn
async def fetch_running_config(
    device_hostname: str,
    ip_address: str,
    port: int = 57400,
) -> str:
    """Fetch the current running config from a device via gNMI GET.

    Returns the configuration as a JSON string for diff comparison.
    Credentials are resolved from the worker's environment inside the gNMI
    helper — never accepted as arguments, which Temporal would persist in
    workflow history (Issue #166).
    """
    activity.logger.info(f"Fetching running config from {device_hostname} ({ip_address}:{port})")
    return await fetch_config_via_gnmi(device_hostname, ip_address, port=port)


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
