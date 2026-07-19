"""Unit tests for deterministic lab management addressing (Issue #178).

The `clab` docker network (172.20.20.0/24) is shared with other containerlab
deployments on the same host, and docker hands out dynamic addresses from
the bottom of the subnet. Without static `mgmt-ipv4` pins, the SoT seed
data's management IPs can end up pointing at *another project's* SR Linux
nodes (same default credentials), so a workflow would push config to a
foreign device.

These tests pin the contract: every spine-leaf-lab node has a static
mgmt-ipv4 above the dynamic-allocation zone, and the Infrahub seed data
agrees with the topology exactly.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[2]
TOPOLOGY_PATH = REPO_ROOT / "containerlab" / "topology.clab.yml"
SEED_DATA_PATH = REPO_ROOT / "backend" / "network_synapse" / "data" / "seed_data.yml"

MGMT_SUBNET = IPv4Network("172.20.20.0/24")
# Other labs on the shared network draw dynamic addresses from the bottom
# of the subnet; static pins must sit above this zone.
DYNAMIC_ZONE_CEILING = IPv4Address("172.20.20.9")

FABRIC_NODES = ("spine01", "leaf01", "leaf02")


@pytest.fixture(scope="module")
def topology() -> dict:
    return yaml.safe_load(TOPOLOGY_PATH.read_text())


@pytest.fixture(scope="module")
def topology_nodes(topology: dict) -> dict:
    return topology["topology"]["nodes"]


@pytest.fixture(scope="module")
def seed_devices() -> dict[str, dict]:
    seed = yaml.safe_load(SEED_DATA_PATH.read_text())
    return {device["name"]: device for device in seed["devices"]}


@pytest.mark.unit
class TestTopologyMgmtPinning:
    def test_mgmt_block_keeps_shared_clab_network(self, topology: dict):
        """The collector stack and other labs coexist on the `clab` network —
        the name and subnet must not change, only addressing determinism."""
        mgmt = topology["mgmt"]
        assert mgmt["network"] == "clab"
        assert mgmt["ipv4-subnet"] == str(MGMT_SUBNET)

    def test_every_node_has_static_mgmt_ip(self, topology_nodes: dict):
        """All nodes pinned — a single dynamic node could race another lab
        (or this lab's own pins) for an address at deploy time."""
        for name, node in topology_nodes.items():
            assert "mgmt-ipv4" in node, f"{name} has no static mgmt-ipv4"

    def test_static_ips_are_above_the_dynamic_zone(self, topology_nodes: dict):
        for name, node in topology_nodes.items():
            address = IPv4Address(node["mgmt-ipv4"])
            assert address in MGMT_SUBNET, f"{name}: {address} outside {MGMT_SUBNET}"
            assert address > DYNAMIC_ZONE_CEILING, f"{name}: {address} inside the dynamic-allocation zone"

    def test_static_ips_are_unique(self, topology_nodes: dict):
        addresses = [node["mgmt-ipv4"] for node in topology_nodes.values()]
        assert len(addresses) == len(set(addresses))


@pytest.mark.unit
class TestSeedDataMatchesTopology:
    @pytest.mark.parametrize("hostname", FABRIC_NODES)
    def test_seed_management_ip_matches_topology_pin(self, hostname: str, topology_nodes: dict, seed_devices: dict):
        pinned = topology_nodes[hostname]["mgmt-ipv4"]
        assert seed_devices[hostname]["management_ip"] == f"{pinned}/24"
