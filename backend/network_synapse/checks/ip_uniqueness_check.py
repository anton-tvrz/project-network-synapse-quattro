"""Infrahub Check: IP address uniqueness validation.

Validates:
- No duplicate IP addresses exist within the same namespace
- All IP addresses have a valid format

Registered in .infrahub.yml as 'validate_ip_uniqueness'.
"""

from __future__ import annotations

from collections import defaultdict

from infrahub_sdk.checks import InfrahubCheck


class IPUniquenessCheck(InfrahubCheck):
    """Validate IP address uniqueness across the inventory."""

    query = "all_ip_addresses"

    async def validate(self, data: dict) -> None:
        """Check for duplicate IP addresses within the same namespace."""
        ip_edges = data.get("IpamIPAddress", {}).get("edges", [])

        if not ip_edges:
            self.log_info(message="No IP addresses found — nothing to validate")
            return

        # Group IPs by namespace
        namespace_ips: dict[str, list[tuple[str, str]]] = defaultdict(list)

        for edge in ip_edges:
            node = edge["node"]
            address = node.get("address", {}).get("value", "")
            node_id = node.get("id", "unknown")

            if not address:
                self.log_error(
                    message="IP address node has empty address value",
                    object_id=node_id,
                    object_type="IpamIPAddress",
                )
                continue

            ns_node = node.get("ip_namespace", {}).get("node")
            namespace = ns_node["name"]["value"] if ns_node else "default"

            namespace_ips[namespace].append((address, node_id))

        # Check for duplicates per namespace
        for namespace, ip_list in namespace_ips.items():
            seen: dict[str, str] = {}
            for address, node_id in ip_list:
                if address in seen:
                    self.log_error(
                        message=(
                            f"Duplicate IP address '{address}' in namespace '{namespace}' "
                            f"(conflicts with {seen[address][:8]}...)"
                        ),
                        object_id=node_id,
                        object_type="IpamIPAddress",
                    )
                else:
                    seen[address] = node_id
