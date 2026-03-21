"""Placeholder unit tests — replace with real tests as modules are built."""

import pytest


@pytest.mark.unit
def test_project_imports():
    """Verify core dependencies are importable."""
    import json

    import jinja2
    import yaml

    assert jinja2 is not None
    assert yaml is not None
    assert json is not None


@pytest.mark.unit
def test_srlinux_tooling_imports():
    """Verify SR Linux tooling dependencies are importable."""
    import grpc
    import pygnmi

    assert pygnmi is not None
    assert grpc is not None


@pytest.mark.unit
def test_sample_device_fixture(sample_device_data):
    """Verify test fixtures are working."""
    assert sample_device_data["name"] == "spine01"
    assert sample_device_data["asn"] == 65000
    assert sample_device_data["platform"] == "nokia_srlinux"


@pytest.mark.unit
def test_topology_has_three_devices(spine_leaf_topology):
    """Verify topology fixture has expected devices."""
    assert len(spine_leaf_topology) == 3
    assert "spine01" in spine_leaf_topology
    assert "leaf01" in spine_leaf_topology
    assert "leaf02" in spine_leaf_topology
