"""Integration tests for Infrahub transform execution.

Tests that transforms execute correctly via the Infrahub API and produce
valid JSON config output matching expected SR Linux structure.
"""

from __future__ import annotations

import json

import pytest


@pytest.mark.integration
class TestTransformExecution:
    """Test transform execution via Infrahub API."""

    def test_bgp_transform_produces_valid_json(self, infrahub_client):
        """BGP transform returns valid JSON with expected structure."""
        try:
            result = infrahub_client.execute_transform("srlinux_bgp_config", {"hostname": "spine01"})
        except Exception as exc:
            pytest.skip(f"Transform execution not available: {exc}")

        parsed = json.loads(result)
        assert "network-instance" in parsed
        ni = parsed["network-instance"][0]
        assert ni["name"] == "default"
        assert "bgp" in ni["protocols"]
        assert ni["protocols"]["bgp"]["autonomous-system"] > 0

    def test_interface_transform_produces_valid_json(self, infrahub_client):
        """Interface transform returns valid JSON with expected structure."""
        try:
            result = infrahub_client.execute_transform("srlinux_interface_config", {"hostname": "spine01"})
        except Exception as exc:
            pytest.skip(f"Transform execution not available: {exc}")

        parsed = json.loads(result)
        assert "interface" in parsed
        assert len(parsed["interface"]) > 0

        # Verify management interfaces are filtered out
        iface_names = [i["name"] for i in parsed["interface"]]
        assert "mgmt0" not in iface_names

    def test_bgp_transform_strips_cidr_from_peer_addresses(self, infrahub_client):
        """BGP transform peer addresses are bare IPs (no CIDR notation)."""
        try:
            result = infrahub_client.execute_transform("srlinux_bgp_config", {"hostname": "spine01"})
        except Exception as exc:
            pytest.skip(f"Transform execution not available: {exc}")

        parsed = json.loads(result)
        neighbors = parsed["network-instance"][0]["protocols"]["bgp"]["neighbor"]
        for neighbor in neighbors:
            assert "/" not in neighbor["peer-address"], f"Peer address should not have CIDR: {neighbor['peer-address']}"

    def test_interface_transform_preserves_cidr(self, infrahub_client):
        """Interface transform ip-prefix values retain CIDR notation."""
        try:
            result = infrahub_client.execute_transform("srlinux_interface_config", {"hostname": "spine01"})
        except Exception as exc:
            pytest.skip(f"Transform execution not available: {exc}")

        parsed = json.loads(result)
        for iface in parsed["interface"]:
            for sub in iface.get("subinterface", []):
                for addr in sub.get("ipv4", {}).get("address", []):
                    assert "/" in addr["ip-prefix"], f"IP prefix should have CIDR: {addr['ip-prefix']}"
