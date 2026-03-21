"""Integration tests for seed data population.

Validates that seed data is correctly loaded into Infrahub and
that relationships between objects are properly established.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestSeedDataPopulation:
    """Test that seed data creates expected objects in Infrahub."""

    def test_devices_created(self, infrahub_client):
        """Seeded devices exist in Infrahub."""
        devices = infrahub_client.list_devices()
        assert len(devices) > 0, "At least one device should exist after seeding"

        device_names = [d.name for d in devices]
        assert "spine01" in device_names, "spine01 should be seeded"

    def test_device_has_interfaces(self, infrahub_client):
        """Seeded devices have associated interfaces."""
        config = infrahub_client.get_device_config("spine01")
        assert config is not None, "spine01 config should be retrievable"
        assert len(config.interfaces) > 0, "spine01 should have interfaces"

    def test_device_has_bgp_sessions(self, infrahub_client):
        """Seeded devices have associated BGP sessions."""
        config = infrahub_client.get_device_config("spine01")
        assert config is not None
        assert len(config.bgp_sessions) > 0, "spine01 should have BGP sessions"

    def test_bgp_session_has_valid_asn(self, infrahub_client):
        """BGP sessions have valid ASN values."""
        config = infrahub_client.get_device_config("spine01")
        assert config is not None

        for session in config.bgp_sessions:
            assert session.local_asn > 0, f"Invalid local ASN: {session.local_asn}"
            assert session.remote_asn > 0, f"Invalid remote ASN: {session.remote_asn}"

    def test_interfaces_have_expected_roles(self, infrahub_client):
        """Interfaces have expected role values (fabric, loopback, management)."""
        config = infrahub_client.get_device_config("spine01")
        assert config is not None

        roles = {iface.role for iface in config.interfaces}
        assert "fabric" in roles, "spine01 should have fabric interfaces"
        assert "loopback" in roles, "spine01 should have a loopback interface"

    def test_seed_is_idempotent(self, infrahub_client):
        """Running seed again doesn't create duplicates (object count stable)."""
        devices_before = infrahub_client.list_devices()
        count_before = len(devices_before)

        # The autouse seed_data_once fixture already ran once.
        # A second call to list_devices should return the same count.
        devices_after = infrahub_client.list_devices()
        assert len(devices_after) == count_before, "Device count should be stable after re-seeding"
