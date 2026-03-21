"""Unit tests for InfrahubResourceManager — pool creation and allocation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from network_synapse.infrahub.resource_manager import (
    InfrahubResourceManager,
    PoolExhaustedError,
    PoolNotFoundError,
)


@pytest.mark.unit
class TestResourceManagerPoolCreation:
    """Test pool creation methods with mocked GraphQL."""

    def test_create_ip_prefix_pool(self):
        """Pool creation mutation is called with correct variables."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            # First call: lookup (no existing pool)
            # Second call: create
            mock_gql.side_effect = [
                {"CoreIPPrefixPool": {"edges": []}},
                {
                    "CoreIPPrefixPoolCreate": {
                        "ok": True,
                        "object": {"id": "pool-123", "display_label": "fabric-underlay"},
                    }
                },
            ]

            pool_id = mgr.create_ip_prefix_pool("fabric-underlay", "Fabric /31s", 31, ["prefix-id-1"])
            assert pool_id == "pool-123"
            assert mock_gql.call_count == 2

    def test_create_ip_prefix_pool_already_exists(self):
        """Existing pool returns its ID without creating a duplicate."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {"CoreIPPrefixPool": {"edges": [{"node": {"id": "existing-pool"}}]}}

            pool_id = mgr.create_ip_prefix_pool("fabric-underlay", "Fabric /31s", 31, ["prefix-id-1"])
            assert pool_id == "existing-pool"
            assert mock_gql.call_count == 1  # Only lookup, no create

    def test_create_number_pool(self):
        """Number pool with start/end range is created correctly."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.side_effect = [
                {"CoreNumberPool": {"edges": []}},
                {
                    "CoreNumberPoolCreate": {
                        "ok": True,
                        "object": {"id": "asn-pool-123", "display_label": "asn-pool"},
                    }
                },
            ]

            pool_id = mgr.create_number_pool("asn-pool", "ASN allocation", 65000, 65534)
            assert pool_id == "asn-pool-123"

    def test_create_ip_address_pool(self):
        """IP address pool is created correctly."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.side_effect = [
                {"CoreIPAddressPool": {"edges": []}},
                {
                    "CoreIPAddressPoolCreate": {
                        "ok": True,
                        "object": {"id": "addr-pool-123", "display_label": "loopback-addresses"},
                    }
                },
            ]

            pool_id = mgr.create_ip_address_pool("loopback-addresses", "Loopback IPs", 32, ["prefix-id-1"])
            assert pool_id == "addr-pool-123"


@pytest.mark.unit
class TestResourceManagerAllocation:
    """Test resource allocation methods with mocked GraphQL."""

    def test_allocate_prefix_returns_result(self):
        """Prefix allocation returns the allocated prefix string."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {
                "IPPrefixPoolGetResource": {
                    "ok": True,
                    "node": {"id": "prefix-alloc-1", "prefix": {"value": "10.0.0.0/31"}},
                }
            }

            result = mgr.allocate_prefix("pool-123", prefix_length=31, identifier="test-link")
            assert result.value == "10.0.0.0/31"
            assert result.pool_id == "pool-123"

    def test_allocate_ip_address_returns_result(self):
        """IP address allocation returns the allocated address."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {
                "IPAddressPoolGetResource": {
                    "ok": True,
                    "node": {"id": "ip-alloc-1", "address": {"value": "10.1.0.1/32"}},
                }
            }

            result = mgr.allocate_ip_address("pool-456", identifier="spine01-lo")
            assert result.value == "10.1.0.1/32"

    def test_allocate_number_returns_result(self):
        """Number allocation returns the allocated integer."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {
                "NumberPoolGetResource": {
                    "ok": True,
                    "node": {"id": "num-alloc-1", "value": 65003},
                }
            }

            result = mgr.allocate_number("pool-789", identifier="new-device")
            assert result.value == 65003

    def test_allocate_from_exhausted_pool_raises(self):
        """Allocation from exhausted pool raises PoolExhaustedError."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {"IPPrefixPoolGetResource": {"ok": False}}

            with pytest.raises(PoolExhaustedError):
                mgr.allocate_prefix("pool-123")


@pytest.mark.unit
class TestResourceManagerProvisioning:
    """Test high-level provisioning method."""

    def test_provision_device(self):
        """Provision device allocates ASN, loopback, and fabric links."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.side_effect = [
                # Lookup ASN pool
                {"CoreNumberPool": {"edges": [{"node": {"id": "asn-pool-id"}}]}},
                # Lookup loopback pool
                {"CoreIPAddressPool": {"edges": [{"node": {"id": "lo-pool-id"}}]}},
                # Lookup fabric pool
                {"CoreIPPrefixPool": {"edges": [{"node": {"id": "fabric-pool-id"}}]}},
                # Allocate ASN
                {"NumberPoolGetResource": {"ok": True, "node": {"id": "n1", "value": 65003}}},
                # Allocate loopback
                {
                    "IPAddressPoolGetResource": {
                        "ok": True,
                        "node": {"id": "a1", "address": {"value": "10.1.0.4/32"}},
                    }
                },
                # Allocate fabric /31 for peer leaf01
                {
                    "IPPrefixPoolGetResource": {
                        "ok": True,
                        "node": {"id": "p1", "prefix": {"value": "10.0.0.8/31"}},
                    }
                },
            ]

            result = mgr.provision_device("leaf03", "leaf", ["spine01"])

            assert result.device_name == "leaf03"
            assert result.asn == 65003
            assert result.loopback_ip == "10.1.0.4/32"
            assert len(result.fabric_links) == 1
            assert result.fabric_links[0].peer_device == "spine01"
            assert result.fabric_links[0].prefix == "10.0.0.8/31"

    def test_provision_device_pool_not_found(self):
        """Provision fails when a required pool doesn't exist."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {"CoreNumberPool": {"edges": []}}

            with pytest.raises(PoolNotFoundError, match="asn-pool"):
                mgr.provision_device("leaf03", "leaf", ["spine01"])


@pytest.mark.unit
class TestResourceManagerPoolLookup:
    """Test pool lookup by name."""

    def test_get_pool_by_name_found(self):
        """Returns pool ID when pool exists."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {"CoreIPPrefixPool": {"edges": [{"node": {"id": "found-pool"}}]}}
            assert mgr.get_pool_by_name("CoreIPPrefixPool", "test") == "found-pool"

    def test_get_pool_by_name_not_found(self):
        """Returns None when pool doesn't exist."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with patch.object(mgr, "_graphql") as mock_gql:
            mock_gql.return_value = {"CoreIPPrefixPool": {"edges": []}}
            assert mgr.get_pool_by_name("CoreIPPrefixPool", "nonexistent") is None

    def test_get_pool_by_name_invalid_type(self):
        """Raises ValueError for unknown pool type."""
        mgr = InfrahubResourceManager(url="http://test:8000", token="test-token")
        with pytest.raises(ValueError, match="Unknown pool type"):
            mgr.get_pool_by_name("CoreInvalidPool", "test")
