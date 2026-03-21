"""Infrahub Python Transform: SR Linux interface configuration generator.

Replaces the local Jinja2-based srlinux_interfaces.j2 template with an
Infrahub-managed transform. Receives GraphQL query results and produces
the SR Linux interface JSON configuration as a string.

Registered in .infrahub.yml as 'srlinux_interface_config'.
"""

from __future__ import annotations

import json

from infrahub_sdk.transforms import InfrahubTransform


class SRLinuxInterfaceTransform(InfrahubTransform):
    """Generate SR Linux interface JSON from Infrahub device data.

    Uses the device_interface_config query which returns:
    - DcimDevice (device metadata)
    - InterfacePhysical (all interfaces for the device)

    Filters to fabric + loopback interfaces only (same as
    DeviceConfig.to_interface_template_vars()).
    """

    query = "device_interface_config"
    url = ""

    async def transform(self, data: dict) -> str:
        """Transform GraphQL query results into SR Linux interface JSON.

        Produces the same JSON structure as srlinux_interfaces.j2 template.
        """
        interface_edges = data.get("InterfacePhysical", {}).get("edges", [])

        interfaces = []
        for edge in interface_edges:
            node = edge["node"]
            role = node.get("role", {}).get("value", "")

            # Filter to fabric + loopback only (skip management, access)
            if role not in ("fabric", "loopback"):
                continue

            name = node["name"]["value"]
            description = node.get("description", {}).get("value", "")
            mtu = node.get("mtu", {}).get("value", 9214) or 9214
            enabled = True  # Default for fabric/loopback

            # Extract first IP address
            ip_edges = node.get("ip_addresses", {}).get("edges", [])
            ip_address = ip_edges[0]["node"]["address"]["value"] if ip_edges else None

            # Build interface entry
            subinterface: dict = {
                "index": 0,
                "description": description,
            }
            if ip_address:
                subinterface["ipv4"] = {
                    "admin-state": "enable",
                    "address": [{"ip-prefix": ip_address}],
                }

            interface_entry = {
                "name": name,
                "description": description,
                "admin-state": "enable" if enabled else "disable",
                "mtu": mtu,
                "subinterface": [subinterface],
            }
            interfaces.append(interface_entry)

        config = {"interface": interfaces}
        return json.dumps(config, indent=2)
