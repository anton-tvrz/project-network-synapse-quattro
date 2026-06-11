"""Unit tests for the pre-deployment hygiene checker.

Covers the BGP and interface JSON validation logic and the combined
`run_hygiene_checks` entry point, including the failure branches that abort
a deployment.
"""

from __future__ import annotations

import json

import pytest

from network_synapse.scripts.hygiene_checker import (
    run_hygiene_checks,
    validate_bgp_hygiene,
    validate_interface_hygiene,
)

# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------


def _bgp_payload(asn: int = 65000, groups: list | None = None, neighbors: list | None = None) -> str:
    bgp: dict = {"autonomous-system": asn}
    bgp["group"] = [{"group-name": "underlay"}] if groups is None else groups
    bgp["neighbor"] = [{"peer-address": "10.0.0.1"}] if neighbors is None else neighbors
    return json.dumps({"network-instance": [{"name": "default", "protocols": {"bgp": bgp}}]})


def _iface_payload(interfaces: list | None = None) -> str:
    if interfaces is None:
        interfaces = [
            {
                "name": "ethernet-1/1",
                "subinterface": [{"ipv4": {"address": [{"ip-prefix": "10.0.0.0/31"}]}}],
            }
        ]
    return json.dumps({"interface": interfaces})


# ---------------------------------------------------------------------------
# validate_bgp_hygiene
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBGPHygiene:
    def test_valid_payload_passes(self) -> None:
        assert validate_bgp_hygiene(_bgp_payload()) is True

    def test_no_network_instance_is_skipped(self) -> None:
        """A payload without network-instance is treated as not-relevant (passes)."""
        assert validate_bgp_hygiene(json.dumps({"interface": []})) is True

    def test_network_instance_without_bgp_is_skipped(self) -> None:
        payload = json.dumps({"network-instance": [{"name": "default", "protocols": {}}]})
        assert validate_bgp_hygiene(payload) is True

    def test_missing_asn_fails(self) -> None:
        payload = json.dumps(
            {"network-instance": [{"name": "default", "protocols": {"bgp": {"group": [{"group-name": "x"}]}}}]}
        )
        assert validate_bgp_hygiene(payload) is False

    def test_zero_asn_fails(self) -> None:
        assert validate_bgp_hygiene(_bgp_payload(asn=0)) is False

    def test_out_of_range_asn_fails(self) -> None:
        assert validate_bgp_hygiene(_bgp_payload(asn=5_000_000_000)) is False

    def test_empty_groups_fails(self) -> None:
        assert validate_bgp_hygiene(_bgp_payload(groups=[])) is False

    def test_invalid_neighbor_ip_fails(self) -> None:
        assert validate_bgp_hygiene(_bgp_payload(neighbors=[{"peer-address": "not-an-ip"}])) is False

    def test_empty_neighbors_passes(self) -> None:
        assert validate_bgp_hygiene(_bgp_payload(neighbors=[])) is True

    def test_invalid_json_fails(self) -> None:
        assert validate_bgp_hygiene("not json {{") is False


# ---------------------------------------------------------------------------
# validate_interface_hygiene
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInterfaceHygiene:
    def test_valid_payload_passes(self) -> None:
        assert validate_interface_hygiene(_iface_payload()) is True

    def test_no_interface_key_is_skipped(self) -> None:
        assert validate_interface_hygiene(json.dumps({"network-instance": []})) is True

    def test_system_interface_name_passes(self) -> None:
        assert validate_interface_hygiene(_iface_payload([{"name": "system0", "subinterface": []}])) is True

    def test_invalid_interface_name_fails(self) -> None:
        assert validate_interface_hygiene(_iface_payload([{"name": "wan0", "subinterface": []}])) is False

    def test_invalid_ipv4_prefix_fails(self) -> None:
        interfaces = [
            {
                "name": "ethernet-1/1",
                "subinterface": [{"ipv4": {"address": [{"ip-prefix": "999.0.0.0/31"}]}}],
            }
        ]
        assert validate_interface_hygiene(_iface_payload(interfaces)) is False

    def test_invalid_json_fails(self) -> None:
        assert validate_interface_hygiene("not json {{") is False


# ---------------------------------------------------------------------------
# run_hygiene_checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunHygieneChecks:
    def test_both_valid_passes(self) -> None:
        assert run_hygiene_checks(_bgp_payload(), _iface_payload()) is True

    def test_bad_bgp_fails(self) -> None:
        assert run_hygiene_checks(_bgp_payload(asn=0), _iface_payload()) is False

    def test_bad_interface_fails(self) -> None:
        assert run_hygiene_checks(_bgp_payload(), _iface_payload([{"name": "wan0", "subinterface": []}])) is False
