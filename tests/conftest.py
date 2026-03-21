"""Shared test fixtures for the network automation project."""

import os

import pytest

from network_synapse.infrahub.models import (
    BGPSessionData,
    DeviceConfig,
    DeviceData,
    InterfaceData,
)

# ─── Containerlab mgmt IPs (DHCP-assigned, may change on redeploy) ───
# Current assignment (OrbStack / Containerlab):
#   leaf01:  172.20.20.2
#   spine01: 172.20.20.3
#   leaf02:  172.20.20.4
# For integration tests, use the clab_topology fixture below.
# For unit tests, fixtures use stable placeholder IPs (mocked, not real).


@pytest.fixture
def sample_device_data():
    """Sample device data matching Infrahub schema (unit tests — mocked)."""
    return {
        "name": "spine01",
        "device_type": "7220 IXR-D3",
        "platform": "nokia_srlinux",
        "management_ip": "172.20.20.3",
        "asn": 65000,
        "role": "spine",
        "status": "active",
        "nos": "srlinux",
        "sw_version": "v25.10.1",
    }


@pytest.fixture
def sample_bgp_session():
    """Sample BGP session data (SR Linux style)."""
    return {
        "local_asn": 65000,
        "remote_asn": 65001,
        "local_ip": "10.0.0.0",
        "remote_ip": "10.0.0.1",
        "description": "spine01 to leaf01",
        "status": "active",
        "network_instance": "default",
        "group": "underlay",
    }


@pytest.fixture
def spine_leaf_topology():
    """Full spine-leaf topology fixture (Nokia SR Linux — unit tests)."""
    return {
        "spine01": {
            "asn": 65000,
            "mgmt_ip": "172.20.20.3",
            "role": "spine",
            "platform": "nokia_srlinux",
            "type": "ixr-d3",
        },
        "leaf01": {
            "asn": 65001,
            "mgmt_ip": "172.20.20.2",
            "role": "leaf",
            "platform": "nokia_srlinux",
            "type": "ixr-d2",
        },
        "leaf02": {
            "asn": 65002,
            "mgmt_ip": "172.20.20.4",
            "role": "leaf",
            "platform": "nokia_srlinux",
            "type": "ixr-d2",
        },
    }


@pytest.fixture
def clab_credentials():
    """SR Linux default credentials for Containerlab nodes."""
    return {
        "username": os.getenv("SRLINUX_USER", "admin"),
        "password": os.getenv("SRLINUX_PASS", "NokiaSrl1!"),
        "gnmi_port": 57400,
        "jsonrpc_port": 443,
    }


# ---------------------------------------------------------------------------
# Config generation fixtures (Issue #12)
# ---------------------------------------------------------------------------


@pytest.fixture
def spine01_device_config():
    """Fully populated DeviceConfig for spine01 — matches seed_data.yml."""
    device = DeviceData(
        id="device-spine01-id",
        name="spine01",
        description="Spine switch - Nokia 7220 IXR-D3",
        management_ip="172.20.20.3/24",
        lab_node_name="clab-spine-leaf-lab-spine01",
        role="spine",
        status="active",
        asn=65000,
        router_id="10.1.0.1",
    )
    interfaces = [
        InterfaceData(
            name="ethernet-1/1",
            description="to leaf01:ethernet-1/49",
            mtu=9214,
            role="fabric",
            ip_address="10.0.0.0/31",
        ),
        InterfaceData(
            name="ethernet-1/2",
            description="to leaf02:ethernet-1/49",
            mtu=9214,
            role="fabric",
            ip_address="10.0.0.2/31",
        ),
        InterfaceData(
            name="ethernet-1/3",
            description="to leaf01:ethernet-1/50",
            mtu=9214,
            role="fabric",
            ip_address="10.0.0.4/31",
        ),
        InterfaceData(
            name="ethernet-1/4",
            description="to leaf02:ethernet-1/50",
            mtu=9214,
            role="fabric",
            ip_address="10.0.0.6/31",
        ),
        InterfaceData(
            name="loopback0",
            description="Router ID - spine01",
            mtu=9214,
            role="loopback",
            ip_address="10.1.0.1/32",
        ),
    ]
    bgp_sessions = [
        BGPSessionData(
            description="spine01:e1-1 <-> leaf01:e1-49 eBGP",
            session_type="EXTERNAL",
            role="backbone",
            local_asn=65000,
            remote_asn=65001,
            local_ip="10.0.0.0/31",
            remote_ip="10.0.0.1/31",
            peer_group="underlay",
        ),
        BGPSessionData(
            description="spine01:e1-3 <-> leaf01:e1-50 eBGP",
            session_type="EXTERNAL",
            role="backbone",
            local_asn=65000,
            remote_asn=65001,
            local_ip="10.0.0.4/31",
            remote_ip="10.0.0.5/31",
            peer_group="underlay",
        ),
        BGPSessionData(
            description="spine01:e1-2 <-> leaf02:e1-49 eBGP",
            session_type="EXTERNAL",
            role="backbone",
            local_asn=65000,
            remote_asn=65002,
            local_ip="10.0.0.2/31",
            remote_ip="10.0.0.3/31",
            peer_group="underlay",
        ),
        BGPSessionData(
            description="spine01:e1-4 <-> leaf02:e1-50 eBGP",
            session_type="EXTERNAL",
            role="backbone",
            local_asn=65000,
            remote_asn=65002,
            local_ip="10.0.0.6/31",
            remote_ip="10.0.0.7/31",
            peer_group="underlay",
        ),
    ]
    return DeviceConfig(device=device, interfaces=interfaces, bgp_sessions=bgp_sessions)


@pytest.fixture
def mock_infrahub_device_response():
    """Raw Infrahub GraphQL response for DcimDevice query (spine01)."""
    return {
        "DcimDevice": {
            "edges": [
                {
                    "node": {
                        "id": "device-spine01-id",
                        "name": {"value": "spine01"},
                        "description": {"value": "Spine switch - Nokia 7220 IXR-D3"},
                        "management_ip": {"value": "172.20.20.3/24"},
                        "lab_node_name": {"value": "clab-spine-leaf-lab-spine01"},
                        "role": {"value": "spine"},
                        "status": {"value": "active"},
                        "asn": {
                            "node": {
                                "asn": {"value": 65000},
                                "name": {"value": "Spine AS"},
                            }
                        },
                    }
                }
            ]
        }
    }


@pytest.fixture
def mock_infrahub_interfaces_response():
    """Raw Infrahub GraphQL response for InterfacePhysical query (spine01)."""
    return {
        "InterfacePhysical": {
            "edges": [
                {
                    "node": {
                        "id": "iface-e1-1",
                        "name": {"value": "ethernet-1/1"},
                        "description": {"value": "to leaf01:ethernet-1/49"},
                        "mtu": {"value": 9214},
                        "role": {"value": "fabric"},
                        "ip_addresses": {"edges": [{"node": {"address": {"value": "10.0.0.0/31"}}}]},
                    }
                },
                {
                    "node": {
                        "id": "iface-lo0",
                        "name": {"value": "loopback0"},
                        "description": {"value": "Router ID - spine01"},
                        "mtu": {"value": 9214},
                        "role": {"value": "loopback"},
                        "ip_addresses": {"edges": [{"node": {"address": {"value": "10.1.0.1/32"}}}]},
                    }
                },
            ]
        }
    }


@pytest.fixture
def mock_infrahub_bgp_sessions_response():
    """Raw Infrahub GraphQL response for RoutingBGPSession query (spine01)."""
    return {
        "RoutingBGPSession": {
            "edges": [
                {
                    "node": {
                        "id": "bgp-sess-1",
                        "description": {"value": "spine01:e1-1 <-> leaf01:e1-49 eBGP"},
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
        }
    }


# ---------------------------------------------------------------------------
# Resource Manager / Pool fixtures (Phase 4)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_prefix_pool_response():
    """Mock GraphQL response for IP prefix pool creation."""
    return {
        "CoreIPPrefixPoolCreate": {
            "ok": True,
            "object": {"id": "pool-prefix-123", "display_label": "fabric-underlay"},
        }
    }


@pytest.fixture
def mock_allocation_response():
    """Mock GraphQL response for prefix allocation."""
    return {
        "IPPrefixPoolGetResource": {
            "ok": True,
            "node": {"id": "alloc-1", "prefix": {"value": "10.0.0.0/31"}},
        }
    }


@pytest.fixture
def mock_bgp_query_result():
    """Mock GraphQL query result for BGP transform (device + sessions + loopback)."""
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
def mock_all_bgp_sessions_result():
    """Mock GraphQL result for all BGP sessions (used by BGP check)."""
    return {
        "RoutingBGPSession": {
            "edges": [
                {
                    "node": {
                        "id": "bgp-1",
                        "description": {"value": "spine01 to leaf01"},
                        "session_type": {"value": "EXTERNAL"},
                        "role": {"value": "backbone"},
                        "status": {"value": "active"},
                        "device": {"node": {"name": {"value": "spine01"}}},
                        "local_as": {"node": {"asn": {"value": 65000}}},
                        "remote_as": {"node": {"asn": {"value": 65001}}},
                        "local_ip": {"node": {"address": {"value": "10.0.0.0/31"}}},
                        "remote_ip": {"node": {"address": {"value": "10.0.0.1/31"}}},
                        "peer_group": {"node": {"name": {"value": "underlay"}}},
                    }
                },
                {
                    "node": {
                        "id": "bgp-2",
                        "description": {"value": "leaf01 to spine01"},
                        "session_type": {"value": "EXTERNAL"},
                        "role": {"value": "backbone"},
                        "status": {"value": "active"},
                        "device": {"node": {"name": {"value": "leaf01"}}},
                        "local_as": {"node": {"asn": {"value": 65001}}},
                        "remote_as": {"node": {"asn": {"value": 65000}}},
                        "local_ip": {"node": {"address": {"value": "10.0.0.1/31"}}},
                        "remote_ip": {"node": {"address": {"value": "10.0.0.0/31"}}},
                        "peer_group": {"node": {"name": {"value": "underlay"}}},
                    }
                },
            ]
        }
    }
