"""Infrahub Check: Interface configuration consistency validation.

Validates:
- Fabric interfaces have IP addresses assigned
- Fabric interfaces have descriptions
- Interface names follow valid naming conventions (ethernet-*/system*/loopback*)

Migrates validation logic from scripts/hygiene_checker.py into an
Infrahub-native check.

Registered in .infrahub.yml as 'validate_interface_consistency'.
"""

from __future__ import annotations

from infrahub_sdk.checks import InfrahubCheck


class InterfaceConsistencyCheck(InfrahubCheck):
    """Validate interface configuration consistency."""

    query = "all_device_interfaces"

    async def validate(self, data: dict) -> None:
        """Check interface data for consistency issues."""
        iface_edges = data.get("InterfacePhysical", {}).get("edges", [])

        if not iface_edges:
            self.log_info(message="No interfaces found — nothing to validate")
            return

        for edge in iface_edges:
            node = edge["node"]
            iface_id = node.get("id", "unknown")
            name = node.get("name", {}).get("value", "")
            role = node.get("role", {}).get("value", "")
            description = node.get("description", {}).get("value", "")
            device_node = node.get("device", {}).get("node")
            device_name = device_node["name"]["value"] if device_node else "unknown"
            iface_label = f"{device_name}:{name}"

            # Check 1: Valid interface name format
            if name and not name.startswith(("ethernet-", "system", "loopback", "mgmt")):
                self.log_error(
                    message=f"Interface '{iface_label}' has unexpected name format",
                    object_id=iface_id,
                    object_type="InterfacePhysical",
                )

            # Check 2: Fabric interfaces must have IP addresses
            if role == "fabric":
                ip_edges = node.get("ip_addresses", {}).get("edges", [])
                if not ip_edges:
                    self.log_error(
                        message=f"Fabric interface '{iface_label}' has no IP address assigned",
                        object_id=iface_id,
                        object_type="InterfacePhysical",
                    )

                # Check 3: Fabric interfaces should have descriptions
                if not description:
                    self.log_error(
                        message=f"Fabric interface '{iface_label}' has no description",
                        object_id=iface_id,
                        object_type="InterfacePhysical",
                    )

            # Check 4: Loopback interfaces must have IP addresses (for router-id)
            if role == "loopback":
                ip_edges = node.get("ip_addresses", {}).get("edges", [])
                if not ip_edges:
                    self.log_error(
                        message=f"Loopback interface '{iface_label}' has no IP address (needed for router-id)",
                        object_id=iface_id,
                        object_type="InterfacePhysical",
                    )
