"""Unit tests for Infrahub checks — BGP, IP uniqueness, interface consistency."""

from __future__ import annotations

import pytest

from network_synapse.checks.bgp_session_check import BGPSessionCheck
from network_synapse.checks.interface_consistency_check import InterfaceConsistencyCheck
from network_synapse.checks.ip_uniqueness_check import IPUniquenessCheck


def _make_bgp_session(
    *,
    description: str = "test session",
    local_asn: int = 65000,
    remote_asn: int = 65001,
    local_ip: str = "10.0.0.0/31",
    remote_ip: str = "10.0.0.1/31",
    session_type: str = "EXTERNAL",
) -> dict:
    """Helper to build a mock BGP session edge."""
    return {
        "node": {
            "id": f"bgp-{description[:8]}",
            "description": {"value": description},
            "session_type": {"value": session_type},
            "role": {"value": "backbone"},
            "status": {"value": "active"},
            "device": {"node": {"name": {"value": "spine01"}}},
            "local_as": {"node": {"asn": {"value": local_asn}}},
            "remote_as": {"node": {"asn": {"value": remote_asn}}},
            "local_ip": {"node": {"address": {"value": local_ip}}},
            "remote_ip": {"node": {"address": {"value": remote_ip}}},
            "peer_group": {"node": {"name": {"value": "underlay"}}},
        }
    }


@pytest.mark.unit
class TestBGPSessionCheck:
    """Test BGP session validation check logic."""

    @pytest.mark.asyncio
    async def test_valid_sessions_pass(self):
        """Well-formed BGP sessions pass all checks."""
        check = BGPSessionCheck()
        data = {"RoutingBGPSession": {"edges": [_make_bgp_session()]}}
        await check.validate(data)
        assert not check.errors

    @pytest.mark.asyncio
    async def test_missing_local_ip_fails(self):
        """Sessions without local_ip are flagged as errors."""
        check = BGPSessionCheck()
        session = _make_bgp_session()
        session["node"]["local_ip"] = {"node": None}
        data = {"RoutingBGPSession": {"edges": [session]}}
        await check.validate(data)
        assert any("missing local_ip" in str(e) for e in check.errors)

    @pytest.mark.asyncio
    async def test_invalid_asn_fails(self):
        """ASN of 0 is flagged as error."""
        check = BGPSessionCheck()
        session = _make_bgp_session(local_asn=0)
        session["node"]["local_as"] = {"node": {"asn": {"value": 0}}}
        data = {"RoutingBGPSession": {"edges": [session]}}
        await check.validate(data)
        assert any("invalid local ASN" in str(e) for e in check.errors)

    @pytest.mark.asyncio
    async def test_external_same_asn_fails(self):
        """EXTERNAL session with same local/remote ASN is flagged."""
        check = BGPSessionCheck()
        data = {
            "RoutingBGPSession": {
                "edges": [_make_bgp_session(local_asn=65000, remote_asn=65000, session_type="EXTERNAL")]
            }
        }
        await check.validate(data)
        assert any("same local and remote ASN" in str(e) for e in check.errors)

    @pytest.mark.asyncio
    async def test_empty_sessions_pass(self):
        """No sessions means nothing to validate."""
        check = BGPSessionCheck()
        await check.validate({"RoutingBGPSession": {"edges": []}})
        assert not check.errors


@pytest.mark.unit
class TestIPUniquenessCheck:
    """Test IP uniqueness validation."""

    @pytest.mark.asyncio
    async def test_unique_ips_pass(self):
        """All unique IPs pass the check."""
        check = IPUniquenessCheck()
        data = {
            "IpamIPAddress": {
                "edges": [
                    {
                        "node": {
                            "id": "ip-1",
                            "address": {"value": "10.0.0.0/31"},
                            "description": {"value": ""},
                            "ip_namespace": {"node": {"name": {"value": "default"}}},
                            "interface": {"node": None},
                        }
                    },
                    {
                        "node": {
                            "id": "ip-2",
                            "address": {"value": "10.0.0.1/31"},
                            "description": {"value": ""},
                            "ip_namespace": {"node": {"name": {"value": "default"}}},
                            "interface": {"node": None},
                        }
                    },
                ]
            }
        }
        await check.validate(data)
        assert not check.errors

    @pytest.mark.asyncio
    async def test_duplicate_ips_fail(self):
        """Duplicate IPs in same namespace fail the check."""
        check = IPUniquenessCheck()
        data = {
            "IpamIPAddress": {
                "edges": [
                    {
                        "node": {
                            "id": "ip-1",
                            "address": {"value": "10.0.0.0/31"},
                            "description": {"value": ""},
                            "ip_namespace": {"node": {"name": {"value": "default"}}},
                            "interface": {"node": None},
                        }
                    },
                    {
                        "node": {
                            "id": "ip-2",
                            "address": {"value": "10.0.0.0/31"},
                            "description": {"value": ""},
                            "ip_namespace": {"node": {"name": {"value": "default"}}},
                            "interface": {"node": None},
                        }
                    },
                ]
            }
        }
        await check.validate(data)
        assert any("Duplicate IP" in str(e) for e in check.errors)


@pytest.mark.unit
class TestInterfaceConsistencyCheck:
    """Test interface consistency validation."""

    @pytest.mark.asyncio
    async def test_valid_interfaces_pass(self):
        """Well-formed interfaces pass all checks."""
        check = InterfaceConsistencyCheck()
        data = {
            "InterfacePhysical": {
                "edges": [
                    {
                        "node": {
                            "id": "iface-1",
                            "name": {"value": "ethernet-1/1"},
                            "description": {"value": "to leaf01"},
                            "mtu": {"value": 9214},
                            "role": {"value": "fabric"},
                            "status": {"value": "active"},
                            "device": {"node": {"name": {"value": "spine01"}}},
                            "ip_addresses": {"edges": [{"node": {"address": {"value": "10.0.0.0/31"}}}]},
                        }
                    }
                ]
            }
        }
        await check.validate(data)
        assert not check.errors

    @pytest.mark.asyncio
    async def test_fabric_without_ip_fails(self):
        """Fabric interface without IP is flagged."""
        check = InterfaceConsistencyCheck()
        data = {
            "InterfacePhysical": {
                "edges": [
                    {
                        "node": {
                            "id": "iface-1",
                            "name": {"value": "ethernet-1/1"},
                            "description": {"value": "to leaf01"},
                            "mtu": {"value": 9214},
                            "role": {"value": "fabric"},
                            "status": {"value": "active"},
                            "device": {"node": {"name": {"value": "spine01"}}},
                            "ip_addresses": {"edges": []},
                        }
                    }
                ]
            }
        }
        await check.validate(data)
        assert any("no IP address" in str(e) for e in check.errors)

    @pytest.mark.asyncio
    async def test_fabric_without_description_fails(self):
        """Fabric interface without description is flagged."""
        check = InterfaceConsistencyCheck()
        data = {
            "InterfacePhysical": {
                "edges": [
                    {
                        "node": {
                            "id": "iface-1",
                            "name": {"value": "ethernet-1/1"},
                            "description": {"value": ""},
                            "mtu": {"value": 9214},
                            "role": {"value": "fabric"},
                            "status": {"value": "active"},
                            "device": {"node": {"name": {"value": "spine01"}}},
                            "ip_addresses": {"edges": [{"node": {"address": {"value": "10.0.0.0/31"}}}]},
                        }
                    }
                ]
            }
        }
        await check.validate(data)
        assert any("no description" in str(e) for e in check.errors)
