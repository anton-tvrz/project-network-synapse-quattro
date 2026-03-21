"""Infrahub Python Transform: SR Linux BGP configuration generator.

Replaces the local Jinja2-based srlinux_bgp.j2 template with an Infrahub-managed
transform. Receives GraphQL query results and produces the SR Linux BGP JSON
configuration as a string.

Registered in .infrahub.yml as 'srlinux_bgp_config'.
"""

from __future__ import annotations

import json

from infrahub_sdk.transforms import InfrahubTransform


def _strip_cidr(ip: str) -> str:
    """Strip prefix length from an IP address: '10.0.0.1/31' -> '10.0.0.1'."""
    return ip.split("/", maxsplit=1)[0] if "/" in ip else ip


class SRLinuxBGPTransform(InfrahubTransform):
    """Generate SR Linux BGP JSON from Infrahub device data.

    Uses the device_bgp_config query which returns:
    - DcimDevice (device metadata with ASN)
    - RoutingBGPSession (BGP sessions for the device)
    - InterfacePhysical (loopback interfaces for router-id derivation)
    """

    query = "device_bgp_config"
    url = ""

    async def transform(self, data: dict) -> str:
        """Transform GraphQL query results into SR Linux BGP JSON.

        Produces the same JSON structure as srlinux_bgp.j2 template.
        """
        # Extract device data
        device_edges = data.get("DcimDevice", {}).get("edges", [])
        if not device_edges:
            return json.dumps({})

        device = device_edges[0]["node"]
        asn_node = device.get("asn", {}).get("node")
        local_asn = asn_node["asn"]["value"] if asn_node else 0

        # Derive router_id from loopback interface
        router_id = ""
        loopback_edges = data.get("InterfacePhysical", {}).get("edges", [])
        for edge in loopback_edges:
            node = edge["node"]
            if node.get("role", {}).get("value") == "loopback":
                ip_edges = node.get("ip_addresses", {}).get("edges", [])
                if ip_edges:
                    router_id = _strip_cidr(ip_edges[0]["node"]["address"]["value"])
                    break

        # Extract BGP sessions
        session_edges = data.get("RoutingBGPSession", {}).get("edges", [])
        neighbors = []
        for edge in session_edges:
            session = edge["node"]
            remote_as_node = session.get("remote_as", {}).get("node")
            remote_ip_node = session.get("remote_ip", {}).get("node")
            peer_group_node = session.get("peer_group", {}).get("node")

            neighbor = {
                "peer-address": _strip_cidr(remote_ip_node["address"]["value"]) if remote_ip_node else "",
                "peer-as": remote_as_node["asn"]["value"] if remote_as_node else 0,
                "peer-group": peer_group_node["name"]["value"] if peer_group_node else "underlay",
                "description": session.get("description", {}).get("value", ""),
            }
            neighbors.append(neighbor)

        # Build SR Linux BGP JSON structure
        config = {
            "network-instance": [
                {
                    "name": "default",
                    "protocols": {
                        "bgp": {
                            "autonomous-system": local_asn,
                            "router-id": router_id,
                            "group": [
                                {
                                    "group-name": "underlay",
                                    "export-policy": "export-all",
                                    "import-policy": "import-all",
                                }
                            ],
                            "neighbor": neighbors,
                        }
                    },
                }
            ]
        }

        return json.dumps(config, indent=2)
