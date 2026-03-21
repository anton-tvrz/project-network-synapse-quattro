"""Temporal activities for post-deployment validation."""

from __future__ import annotations

from temporalio import activity

from network_synapse.scripts.validate_state import check_bgp_summary, check_interface_state


@activity.defn
async def validate_bgp(device_hostname: str, ip_address: str) -> bool:
    """Validate BGP sessions are established on a device after deployment."""
    activity.logger.info(f"Validating BGP state on {device_hostname} ({ip_address})")
    result = check_bgp_summary(ip_address)
    if not result:
        raise RuntimeError(f"BGP validation failed on {device_hostname}")
    return True


@activity.defn
async def validate_interfaces(
    device_hostname: str,
    ip_address: str,
    intended_interfaces: list[dict],
) -> dict:
    """Validate interface states match intended config from Infrahub.

    Args:
        device_hostname: Device hostname (for logging/error messages).
        ip_address: Device management IP for gNMI connection.
        intended_interfaces: List of intended interface dicts from InterfacesTemplateVars.

    Returns:
        Structured result dict with keys: passed, device, details.

    Raises:
        RuntimeError: If validation fails (triggers workflow rollback).
    """
    activity.logger.info(f"Validating interface state on {device_hostname} ({ip_address})")
    result = check_interface_state(ip_address, intended_interfaces)
    if not result["passed"]:
        for detail in result.get("details", []):
            if detail["status"] == "fail":
                activity.logger.error(
                    f"  FAIL: {detail['name']} — {detail['reason']} "
                    f"(admin={detail['admin_state']}, oper={detail['oper_state']})"
                )
        raise RuntimeError(f"Interface validation failed on {device_hostname}")
    return result
