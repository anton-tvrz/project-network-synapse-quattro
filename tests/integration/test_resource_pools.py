"""Integration tests for Infrahub resource pool operations.

Tests pool creation, lookup, and allocation against a real Infrahub instance.
These tests require seed data to be loaded (handled by session fixtures).
"""

from __future__ import annotations

import pytest

from network_synapse.infrahub.resource_manager import PoolNotFoundError


@pytest.mark.integration
class TestPoolCreation:
    """Test resource pool creation against real Infrahub."""

    def test_create_number_pool(self, resource_manager):
        """Create a number pool and verify it can be looked up."""
        pool_id = resource_manager.create_number_pool("test-asn-pool", "Integration test ASN pool", 64512, 64520)
        assert pool_id is not None

        # Verify lookup returns the same pool
        found_id = resource_manager.get_pool_by_name("CoreNumberPool", "test-asn-pool")
        assert found_id == pool_id

    def test_create_number_pool_idempotent(self, resource_manager):
        """Creating the same pool twice returns the existing ID."""
        pool_id1 = resource_manager.create_number_pool("test-asn-pool-idem", "Idempotency test", 64512, 64520)
        pool_id2 = resource_manager.create_number_pool("test-asn-pool-idem", "Idempotency test", 64512, 64520)
        assert pool_id1 == pool_id2

    def test_lookup_nonexistent_pool_returns_none(self, resource_manager):
        """Looking up a pool that doesn't exist returns None."""
        result = resource_manager.get_pool_by_name("CoreNumberPool", "nonexistent-pool-xyz")
        assert result is None

    def test_lookup_invalid_pool_type_raises(self, resource_manager):
        """Looking up an invalid pool type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown pool type"):
            resource_manager.get_pool_by_name("CoreInvalidPool", "test")


@pytest.mark.integration
class TestNumberAllocation:
    """Test number allocation from pools."""

    def test_allocate_number_returns_value(self, resource_manager):
        """Allocating from a number pool returns an integer in range."""
        pool_id = resource_manager.create_number_pool("test-alloc-numbers", "Allocation test", 64512, 64520)

        result = resource_manager.allocate_number(pool_id, identifier="integ-test-1")
        assert isinstance(result.value, int)
        assert 64512 <= result.value <= 64520
        assert result.pool_id == pool_id

    def test_sequential_allocations_are_unique(self, resource_manager):
        """Sequential allocations return different values."""
        pool_id = resource_manager.create_number_pool("test-seq-numbers", "Sequential test", 64512, 64520)

        result1 = resource_manager.allocate_number(pool_id, identifier="seq-1")
        result2 = resource_manager.allocate_number(pool_id, identifier="seq-2")
        assert result1.value != result2.value


@pytest.mark.integration
class TestProvisionDevice:
    """Test high-level device provisioning (requires pools to exist)."""

    def test_provision_missing_pool_raises(self, resource_manager):
        """Provisioning fails when required pools don't exist."""
        with pytest.raises(PoolNotFoundError):
            resource_manager.provision_device(
                "test-device",
                "leaf",
                ["spine01"],
                asn_pool_name="definitely-does-not-exist",
            )
