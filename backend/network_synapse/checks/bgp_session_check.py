"""Infrahub Check: BGP session data consistency validation.

Validates:
- Every BGP session has valid local/remote ASN values
- Every BGP session has local and remote IP addresses assigned
- Session types match the ASN relationship (EXTERNAL = different ASNs)

Migrates validation logic from scripts/hygiene_checker.py into an
Infrahub-native check.

Registered in .infrahub.yml as 'validate_bgp_sessions'.
"""

from __future__ import annotations

from infrahub_sdk.checks import InfrahubCheck


class BGPSessionCheck(InfrahubCheck):
    """Validate BGP session data consistency."""

    query = "all_bgp_sessions"

    async def validate(self, data: dict) -> None:
        """Run BGP session validation checks.

        Uses self.log_error() to report failures and self.log_info() for context.
        Any call to log_error() causes the check to fail.
        """
        sessions = data.get("RoutingBGPSession", {}).get("edges", [])

        if not sessions:
            self.log_info(message="No BGP sessions found — nothing to validate")
            return

        seen_pairs: set[tuple[str, str]] = set()

        for edge in sessions:
            session = edge["node"]
            session_id = session.get("id", "unknown")
            desc = session.get("description", {}).get("value", "unnamed")

            # Check 1: Valid local ASN
            local_as_node = session.get("local_as", {}).get("node")
            local_asn = local_as_node["asn"]["value"] if local_as_node else None
            if not local_asn or local_asn < 1:
                self.log_error(
                    message=f"BGP session '{desc}' has invalid local ASN: {local_asn}",
                    object_id=session_id,
                    object_type="RoutingBGPSession",
                )

            # Check 2: Valid remote ASN
            remote_as_node = session.get("remote_as", {}).get("node")
            remote_asn = remote_as_node["asn"]["value"] if remote_as_node else None
            if not remote_asn or remote_asn < 1:
                self.log_error(
                    message=f"BGP session '{desc}' has invalid remote ASN: {remote_asn}",
                    object_id=session_id,
                    object_type="RoutingBGPSession",
                )

            # Check 3: Local IP present
            local_ip_node = session.get("local_ip", {}).get("node")
            local_ip = local_ip_node["address"]["value"] if local_ip_node else None
            if not local_ip:
                self.log_error(
                    message=f"BGP session '{desc}' is missing local_ip",
                    object_id=session_id,
                    object_type="RoutingBGPSession",
                )

            # Check 4: Remote IP present
            remote_ip_node = session.get("remote_ip", {}).get("node")
            remote_ip = remote_ip_node["address"]["value"] if remote_ip_node else None
            if not remote_ip:
                self.log_error(
                    message=f"BGP session '{desc}' is missing remote_ip",
                    object_id=session_id,
                    object_type="RoutingBGPSession",
                )

            # Check 5: EXTERNAL sessions should have different local/remote ASN
            session_type = session.get("session_type", {}).get("value", "")
            if session_type == "EXTERNAL" and local_asn and remote_asn and local_asn == remote_asn:
                self.log_error(
                    message=f"EXTERNAL BGP session '{desc}' has same local and remote ASN ({local_asn})",
                    object_id=session_id,
                    object_type="RoutingBGPSession",
                )

            # Track pairs for symmetry check
            if local_ip and remote_ip:
                seen_pairs.add((local_ip, remote_ip))

        # Check 6: Log info about session symmetry (warning, not error)
        for local_ip, remote_ip in seen_pairs:
            reverse = (remote_ip, local_ip)
            if reverse not in seen_pairs:
                self.log_info(
                    message=f"BGP session {local_ip} -> {remote_ip} has no reverse session ({remote_ip} -> {local_ip})"
                )
