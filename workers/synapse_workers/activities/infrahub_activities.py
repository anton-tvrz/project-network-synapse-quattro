"""Temporal activities for interacting with Infrahub source of truth.

These activities run in Temporal's thread-pool executor, so synchronous
httpx calls (used by InfrahubConfigClient and InfrahubResourceManager) are fine here.
"""

from __future__ import annotations

import os

from temporalio import activity

from network_synapse.infrahub.client import InfrahubConfigClient
from network_synapse.infrahub.resource_manager import InfrahubResourceManager


@activity.defn
async def fetch_device_config(device_hostname: str) -> dict:
    """Fetch intended configuration for a device from Infrahub.

    Queries Infrahub GraphQL API for device metadata, interfaces, and BGP
    sessions.  Returns a dict with 'bgp' and 'interfaces' keys containing
    the template variable dicts ready for Jinja2 rendering.

    Returns:
        dict with keys:
            - hostname: device hostname
            - bgp: BGPTemplateVars as dict
            - interfaces: InterfacesTemplateVars as dict
    """
    client = InfrahubConfigClient(
        url=os.getenv("INFRAHUB_URL", "http://localhost:8000"),
        token=os.getenv("INFRAHUB_TOKEN", ""),
    )
    try:
        config = client.get_device_config(device_hostname)
        return {
            "hostname": device_hostname,
            "bgp": config.to_bgp_template_vars().model_dump(),
            "interfaces": config.to_interface_template_vars().model_dump(),
        }
    finally:
        client.close()


@activity.defn
async def update_device_status(device_hostname: str, status: str) -> None:
    """Update device status in Infrahub.

    Sends a DcimDeviceUpdate GraphQL mutation to change the device status field.
    Emits a structured audit log entry recording the old and new status.

    Args:
        device_hostname: Device hostname to update.
        status: Target status (active, provisioning, maintenance, drained).

    Raises:
        ValueError: If status is invalid (non-retryable).
        DeviceNotFoundError: If device not found (non-retryable).
        RuntimeError: On Infrahub API errors (retryable by Temporal).
    """
    client = InfrahubConfigClient(
        url=os.getenv("INFRAHUB_URL", "http://localhost:8000"),
        token=os.getenv("INFRAHUB_TOKEN", ""),
    )
    try:
        device = client.update_device_status(device_hostname, status)
        activity.logger.info(
            "Device status updated: device=%s old_status=%s new_status=%s",
            device_hostname,
            device.status,
            status,
        )
    finally:
        client.close()


@activity.defn
async def allocate_device_resources(
    device_name: str,
    role: str,
    peer_devices: list[str],
) -> dict:
    """Allocate resources from Infrahub pools for a new device.

    Uses the resource manager to dynamically allocate:
    - ASN from the asn-pool
    - Loopback /32 from the loopback-addresses pool
    - Fabric /31 per peer from the fabric-underlay pool

    Args:
        device_name: Name of the device to provision.
        role: Device role (spine, leaf, etc.).
        peer_devices: List of peer device names for fabric links.

    Returns:
        dict with provisioning result (asn, loopback_ip, fabric_links).
    """
    mgr = InfrahubResourceManager(
        url=os.getenv("INFRAHUB_URL", "http://localhost:8000"),
        token=os.getenv("INFRAHUB_TOKEN", ""),
    )
    try:
        result = mgr.provision_device(device_name, role, peer_devices)
        activity.logger.info(
            "Resources allocated: device=%s asn=%d loopback=%s fabric_links=%d",
            device_name,
            result.asn,
            result.loopback_ip,
            len(result.fabric_links),
        )
        return result.model_dump()
    finally:
        mgr.close()
