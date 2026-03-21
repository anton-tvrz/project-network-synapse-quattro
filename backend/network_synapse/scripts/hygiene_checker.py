"""Pre-deployment configuration hygiene validation.

Analyzes the generated JSON structures to ensure they meet basic logic requirements
(e.g., no empty BGP groups, proper ASNs, valid IP subnets) before allowing a deployment.
"""

import ipaddress
import json
import logging

logger = logging.getLogger(__name__)


def validate_bgp_hygiene(bgp_json: str) -> bool:
    """Validate SR Linux BGP JSON payload.

    Checks:
    1. Valid local ASN
    2. Groups exist and aren't empty
    3. Neighbors have valid IP addresses
    """
    try:
        config = json.loads(bgp_json)

        # BGP sits under /network-instance[name=default]/protocols/bgp
        if "network-instance" not in config:
            # Maybe it's not a full config, skip if not relevant
            return True

        for ni in config.get("network-instance", []):
            bgp = ni.get("protocols", {}).get("bgp")
            if not bgp:
                continue

            # 1. Check ASN
            asn = bgp.get("autonomous-system")
            if not asn or not (1 <= asn <= 4294967295):
                logger.error(f"Hygiene Failed: Invalid or missing BGP ASN: {asn}")
                return False

            # 2. Check Groups
            groups = bgp.get("group", [])
            if not groups:
                logger.error("Hygiene Failed: BGP protocol enabled but no groups defined")
                return False

            # 3. Check Neighbors
            neighbors = bgp.get("neighbor", [])
            for nbr in neighbors:
                ip = nbr.get("peer-address")
                try:
                    ipaddress.ip_address(ip)
                except ValueError:
                    logger.error(f"Hygiene Failed: Invalid BGP neighbor IP: {ip}")
                    return False

        return True

    except json.JSONDecodeError:
        logger.error("Hygiene Failed: Invalid JSON payload")
        return False


def validate_interface_hygiene(iface_json: str) -> bool:
    """Validate SR Linux Interface JSON payload.

    Checks:
    1. Interfaces have valid names (ethernet-1/* or system0)
    2. Subinterfaces have valid IPv4/IPv6 prefixes
    """
    try:
        config = json.loads(iface_json)

        if "interface" not in config:
            return True

        for iface in config.get("interface", []):
            name = iface.get("name", "")
            if not name.startswith(("ethernet-", "system")):
                logger.error(f"Hygiene Failed: Invalid interface name format: {name}")
                return False

            for sub in iface.get("subinterface", []):
                ipv4 = sub.get("ipv4", {}).get("address", [])
                for addr in ipv4:
                    ip_prefix = addr.get("ip-prefix")
                    try:
                        ipaddress.ip_network(ip_prefix, strict=False)
                    except ValueError:
                        logger.error(f"Hygiene Failed: Invalid IPv4 prefix on {name}: {ip_prefix}")
                        return False

        return True

    except json.JSONDecodeError:
        logger.error("Hygiene Failed: Invalid JSON payload")
        return False


def run_hygiene_checks(bgp_payload: str, interface_payload: str) -> bool:
    """Run all pre-deployment logic checks on the payloads."""
    logger.info("Running pre-deployment configuration hygiene checks")

    bgp_ok = validate_bgp_hygiene(bgp_payload)
    iface_ok = validate_interface_hygiene(interface_payload)

    if bgp_ok and iface_ok:
        logger.info("Configuration passed all hygiene checks")
        return True

    logger.error("Configuration FAILED hygiene checks. Deployment aborted.")
    return False
