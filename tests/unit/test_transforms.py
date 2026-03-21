"""Unit tests for Infrahub transforms — BGP and interface config generation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from network_synapse.transforms.srlinux_bgp_transform import SRLinuxBGPTransform
from network_synapse.transforms.srlinux_interface_transform import SRLinuxInterfaceTransform


def _make_transform(cls):
    """Instantiate a transform with mocked SDK dependencies."""
    mock_client = MagicMock()
    mock_node = MagicMock()
    return cls(client=mock_client, infrahub_node=mock_node)


@pytest.fixture
def mock_bgp_query_result():
    """Mock GraphQL query result for device_bgp_config."""
    return {
        "DcimDevice": {
            "edges": [
                {
                    "node": {
                        "id": "dev-1",
                        "name": {"value": "spine01"},
                        "description": {"value": "Spine switch"},
                        "role": {"value": "spine"},
                        "status": {"value": "active"},
                        "asn": {"node": {"asn": {"value": 65000}, "name": {"value": "Spine AS"}}},
                    }
                }
            ]
        },
        "RoutingBGPSession": {
            "edges": [
                {
                    "node": {
                        "id": "bgp-1",
                        "description": {"value": "spine01 to leaf01"},
                        "session_type": {"value": "EXTERNAL"},
                        "role": {"value": "backbone"},
                        "status": {"value": "active"},
                        "local_as": {"node": {"asn": {"value": 65000}}},
                        "remote_as": {"node": {"asn": {"value": 65001}}},
                        "local_ip": {"node": {"address": {"value": "10.0.0.0/31"}}},
                        "remote_ip": {"node": {"address": {"value": "10.0.0.1/31"}}},
                        "peer_group": {"node": {"name": {"value": "underlay"}}},
                    }
                }
            ]
        },
        "InterfacePhysical": {
            "edges": [
                {
                    "node": {
                        "name": {"value": "loopback0"},
                        "role": {"value": "loopback"},
                        "ip_addresses": {"edges": [{"node": {"address": {"value": "10.1.0.1/32"}}}]},
                    }
                }
            ]
        },
    }


@pytest.fixture
def mock_interface_query_result():
    """Mock GraphQL query result for device_interface_config."""
    return {
        "DcimDevice": {"edges": [{"node": {"id": "dev-1", "name": {"value": "spine01"}}}]},
        "InterfacePhysical": {
            "edges": [
                {
                    "node": {
                        "id": "iface-1",
                        "name": {"value": "ethernet-1/1"},
                        "description": {"value": "to leaf01"},
                        "mtu": {"value": 9214},
                        "role": {"value": "fabric"},
                        "ip_addresses": {"edges": [{"node": {"address": {"value": "10.0.0.0/31"}}}]},
                    }
                },
                {
                    "node": {
                        "id": "iface-2",
                        "name": {"value": "loopback0"},
                        "description": {"value": "Router ID"},
                        "mtu": {"value": 9214},
                        "role": {"value": "loopback"},
                        "ip_addresses": {"edges": [{"node": {"address": {"value": "10.1.0.1/32"}}}]},
                    }
                },
                {
                    "node": {
                        "id": "iface-3",
                        "name": {"value": "mgmt0"},
                        "description": {"value": "Management"},
                        "mtu": {"value": 1500},
                        "role": {"value": "management"},
                        "ip_addresses": {"edges": [{"node": {"address": {"value": "172.20.20.3/24"}}}]},
                    }
                },
            ]
        },
    }


@pytest.mark.unit
class TestSRLinuxBGPTransform:
    """Test BGP transform produces valid SR Linux JSON."""

    @pytest.mark.asyncio
    async def test_transform_produces_valid_json(self, mock_bgp_query_result):
        """Transform output is valid JSON with correct structure."""
        transform = _make_transform(SRLinuxBGPTransform)
        result = await transform.transform(mock_bgp_query_result)
        parsed = json.loads(result)

        assert "network-instance" in parsed
        ni = parsed["network-instance"][0]
        assert ni["name"] == "default"
        assert ni["protocols"]["bgp"]["autonomous-system"] == 65000
        assert ni["protocols"]["bgp"]["router-id"] == "10.1.0.1"

    @pytest.mark.asyncio
    async def test_transform_strips_cidr_from_peer_address(self, mock_bgp_query_result):
        """Peer addresses in output have bare IPs (no CIDR)."""
        transform = _make_transform(SRLinuxBGPTransform)
        result = await transform.transform(mock_bgp_query_result)
        parsed = json.loads(result)

        neighbors = parsed["network-instance"][0]["protocols"]["bgp"]["neighbor"]
        assert len(neighbors) == 1
        assert neighbors[0]["peer-address"] == "10.0.0.1"  # No /31

    @pytest.mark.asyncio
    async def test_transform_empty_device(self):
        """Empty device data produces empty JSON."""
        transform = _make_transform(SRLinuxBGPTransform)
        result = await transform.transform({"DcimDevice": {"edges": []}})
        assert json.loads(result) == {}

    @pytest.mark.asyncio
    async def test_transform_empty_sessions(self, mock_bgp_query_result):
        """Empty BGP sessions produce valid JSON with empty neighbor list."""
        mock_bgp_query_result["RoutingBGPSession"]["edges"] = []
        transform = _make_transform(SRLinuxBGPTransform)
        result = await transform.transform(mock_bgp_query_result)
        parsed = json.loads(result)
        neighbors = parsed["network-instance"][0]["protocols"]["bgp"]["neighbor"]
        assert neighbors == []


@pytest.mark.unit
class TestSRLinuxInterfaceTransform:
    """Test interface transform produces valid SR Linux JSON."""

    @pytest.mark.asyncio
    async def test_transform_filters_management_interfaces(self, mock_interface_query_result):
        """Management interfaces are excluded from output."""
        transform = _make_transform(SRLinuxInterfaceTransform)
        result = await transform.transform(mock_interface_query_result)
        parsed = json.loads(result)

        iface_names = [i["name"] for i in parsed["interface"]]
        assert "mgmt0" not in iface_names
        assert "ethernet-1/1" in iface_names
        assert "loopback0" in iface_names

    @pytest.mark.asyncio
    async def test_transform_preserves_cidr_on_ip_prefix(self, mock_interface_query_result):
        """Interface ip-prefix retains CIDR notation."""
        transform = _make_transform(SRLinuxInterfaceTransform)
        result = await transform.transform(mock_interface_query_result)
        parsed = json.loads(result)

        eth_iface = next(i for i in parsed["interface"] if i["name"] == "ethernet-1/1")
        ip_prefix = eth_iface["subinterface"][0]["ipv4"]["address"][0]["ip-prefix"]
        assert ip_prefix == "10.0.0.0/31"  # Full CIDR preserved

    @pytest.mark.asyncio
    async def test_transform_empty_interfaces(self):
        """Empty interface list produces valid JSON."""
        transform = _make_transform(SRLinuxInterfaceTransform)
        result = await transform.transform({"InterfacePhysical": {"edges": []}})
        parsed = json.loads(result)
        assert parsed == {"interface": []}
