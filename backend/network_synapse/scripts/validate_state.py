"""Post-deployment state validation for Nokia SR Linux devices via gNMI."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from pygnmi.client import gNMIclient

logger = logging.getLogger(__name__)


def _extract_gnmi_val(result: dict) -> Any | None:
    """Extract the first 'val' payload from a gNMI GET response."""
    for notif in result.get("notification", []):
        for update in notif.get("update", []):
            if "val" in update:
                return update["val"]
    return None


def _evaluate_bgp_neighbors(ip_address: str, neighbors: Any) -> bool:
    """Parse a neighbor data block and verify all sessions are Established."""
    if not neighbors:
        logger.warning(f"No BGP neighbors found on {ip_address}")
        return False

    if isinstance(neighbors, list):
        peer_list = neighbors
    elif isinstance(neighbors, dict):
        peer_list = list(neighbors.values())
    else:
        logger.error(f"Unexpected data format from {ip_address}: {type(neighbors)}")
        return False

    all_ok = True
    for peer in peer_list:
        state = peer.get("session-state", "UNKNOWN")
        addr = peer.get("peer-address", "unknown")
        if state.lower() != "established":
            logger.error(f"BGP peer {addr} on {ip_address} is {state}")
            all_ok = False
        else:
            logger.info(f"BGP peer {addr} on {ip_address} is ESTABLISHED")
    return all_ok


def check_bgp_summary(
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
    port: int = 57400,
) -> bool:
    """Check if all configured BGP sessions are Established."""
    logger.info(f"Checking BGP state on {ip_address}")
    try:
        with gNMIclient(target=(ip_address, port), username=username, password=password, insecure=True) as gc:
            path = "/network-instance[name=default]/protocols/bgp/neighbor"
            result = gc.get(path=[path], datatype="state")

            neighbors = _extract_gnmi_val(result)
            if neighbors is not None:
                return _evaluate_bgp_neighbors(ip_address, neighbors)

            logger.error(f"No BGP state data found on {ip_address}")
            return False
    except Exception as e:
        logger.error(f"Failed to query {ip_address}: {e!s}")
        return False


# ---------------------------------------------------------------------------
# Interface state validation
# ---------------------------------------------------------------------------


class InterfaceDetail(TypedDict):
    """Structured result for a single interface validation check."""

    name: str
    status: str  # "pass" or "fail"
    reason: str
    admin_state: str
    oper_state: str


def _make_detail(
    name: str,
    status: str,
    reason: str = "",
    admin_state: str = "",
    oper_state: str = "",
) -> InterfaceDetail:
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "admin_state": admin_state,
        "oper_state": oper_state,
    }


def _build_device_iface_lookup(gnmi_interfaces: Any) -> dict[str, dict] | None:
    """Build a name-keyed lookup dict from gNMI interface data.

    Handles list-of-dicts (common) and dict-keyed-by-name (defensive).
    Returns None if the format is unrecognised.
    """
    device_ifaces: dict[str, dict] = {}
    if isinstance(gnmi_interfaces, list):
        for iface in gnmi_interfaces:
            if isinstance(iface, dict) and "name" in iface:
                device_ifaces[iface["name"]] = iface
    elif isinstance(gnmi_interfaces, dict):
        for iface_name, iface in gnmi_interfaces.items():
            if isinstance(iface, dict):
                normalized_name = iface.get("name", iface_name)
                device_ifaces[normalized_name] = {"name": normalized_name, **iface}
    else:
        return None
    return device_ifaces


def _evaluate_interface_state(
    ip_address: str,
    gnmi_interfaces: Any,
    intended_interfaces: list[dict],
) -> dict:
    """Compare gNMI interface state against intended config from Infrahub.

    Args:
        ip_address: Device management IP (for logging).
        gnmi_interfaces: Parsed gNMI GET response value for /interface[name=*].
        intended_interfaces: List of intended interface dicts from InterfacesTemplateVars.

    Returns:
        dict with keys: passed (bool), device (str), details (list[dict]).
    """
    device_ifaces = _build_device_iface_lookup(gnmi_interfaces)
    if device_ifaces is None:
        logger.error(f"Unexpected interface data format from {ip_address}: {type(gnmi_interfaces)}")
        return {
            "passed": False,
            "device": ip_address,
            "details": [_make_detail("N/A", "fail", f"Unexpected data format: {type(gnmi_interfaces)}")],
        }

    details: list[InterfaceDetail] = []

    for intended in intended_interfaces:
        if not isinstance(intended, dict):
            logger.error(f"Malformed intended interface entry on {ip_address}: {intended!r}")
            details.append(_make_detail("N/A", "fail", "malformed intended interface entry"))
            continue
        name = intended.get("name")
        if not name:
            logger.error(f"Malformed intended interface entry on {ip_address}: missing name ({intended!r})")
            details.append(_make_detail("N/A", "fail", "missing interface name in intended state"))
            continue
        enabled = intended.get("enabled", True)
        actual = device_ifaces.get(name)

        if actual is None:
            logger.error(f"Interface {name} not found on {ip_address}")
            details.append(_make_detail(name, "fail", "interface not found on device"))
            continue

        admin = actual.get("admin-state", "unknown")
        oper = actual.get("oper-state", "unknown")

        if enabled and admin != "enable":
            logger.error(f"{name} on {ip_address}: admin-state is {admin}, expected enable")
            details.append(_make_detail(name, "fail", f"admin-state is {admin}, expected enable", admin, oper))
        elif enabled and oper != "up":
            logger.error(f"{name} on {ip_address}: admin-up but oper-down")
            details.append(_make_detail(name, "fail", "admin-up but oper-down", admin, oper))
        elif not enabled and admin == "enable":
            logger.error(f"{name} on {ip_address}: admin-state is enable, expected disable")
            details.append(_make_detail(name, "fail", "admin-state is enable, expected disable", admin, oper))
        else:
            logger.info(f"{name} on {ip_address}: OK (admin={admin}, oper={oper})")
            details.append(_make_detail(name, "pass", "", admin, oper))

    passed = all(d["status"] == "pass" for d in details)
    return {"passed": passed, "device": ip_address, "details": details}


def check_interface_state(
    ip_address: str,
    intended_interfaces: list[dict],
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
    port: int = 57400,
) -> dict:
    """Check if device interface states match intended config.

    Args:
        ip_address: Device management IP.
        intended_interfaces: List of intended interface dicts (from InterfacesTemplateVars).

    Returns:
        dict with keys: passed (bool), device (str), details (list[dict]).
    """
    logger.info(f"Checking interface state on {ip_address}")
    try:
        with gNMIclient(target=(ip_address, port), username=username, password=password, insecure=True) as gc:
            result = gc.get(path=["/interface[name=*]"], datatype="state")

            gnmi_interfaces = _extract_gnmi_val(result)
            if gnmi_interfaces is not None:
                return _evaluate_interface_state(ip_address, gnmi_interfaces, intended_interfaces)

            logger.error(f"No interface state data found on {ip_address}")
            return {
                "passed": False,
                "device": ip_address,
                "details": [_make_detail("N/A", "fail", "No interface state data in gNMI response")],
            }
    except Exception as e:
        logger.error(f"Failed to query {ip_address}: {e!s}")
        return {
            "passed": False,
            "device": ip_address,
            "details": [_make_detail("N/A", "fail", f"gNMI connection error: {e!s}")],
        }
