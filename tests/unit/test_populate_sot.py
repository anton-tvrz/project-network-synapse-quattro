"""Unit tests for the Infrahub seed-data population script.

Covers the GraphQL helper, the get_or_create upsert primitive, and the
populate_* functions, with the Infrahub API mocked at the HTTP client level.
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import Mock, patch

import pytest

from network_synapse.data import populate_sot

BASE_URL = "http://infrahub.test:8000"

# ---------------------------------------------------------------------------
# HTTP client doubles
# ---------------------------------------------------------------------------


def _client_returning(*payloads: dict) -> Mock:
    """Mock httpx.Client whose successive post() calls return these JSON bodies."""
    client = Mock()
    client.post.side_effect = [Mock(json=Mock(return_value=p)) for p in payloads]
    return client


def _exists_response(type_name: str, obj_id: str) -> dict:
    return {"data": {type_name: {"edges": [{"node": {"id": obj_id}}]}}}


def _not_found_response(type_name: str) -> dict:
    return {"data": {type_name: {"edges": []}}}


def _create_response(type_name: str, obj_id: str) -> dict:
    return {"data": {f"{type_name}Create": {"ok": True, "object": {"id": obj_id, "display_label": "x"}}}}


# ---------------------------------------------------------------------------
# graphql helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGraphql:
    def test_returns_data_on_success(self) -> None:
        client = _client_returning({"data": {"ok": True}})

        result = populate_sot.graphql(client, BASE_URL, "query { ok }")

        assert result == {"ok": True}
        _, kwargs = client.post.call_args
        assert kwargs["json"] == {"query": "query { ok }"}

    def test_includes_variables_in_payload(self) -> None:
        client = _client_returning({"data": {}})

        populate_sot.graphql(client, BASE_URL, "mutation M($d: I!) { x }", variables={"d": 1})

        _, kwargs = client.post.call_args
        assert kwargs["json"]["variables"] == {"d": 1}

    def test_posts_to_graphql_endpoint(self) -> None:
        client = _client_returning({"data": {}})

        populate_sot.graphql(client, BASE_URL, "query { ok }")

        args, _ = client.post.call_args
        assert args[0] == f"{BASE_URL}/graphql"

    def test_raises_on_graphql_errors(self) -> None:
        client = _client_returning({"errors": [{"message": "boom"}, {"message": "bad"}]})

        with pytest.raises(RuntimeError, match="boom; bad"):
            populate_sot.graphql(client, BASE_URL, "query { ok }")

    def test_missing_data_key_returns_empty_dict(self) -> None:
        client = _client_returning({})

        assert populate_sot.graphql(client, BASE_URL, "query { ok }") == {}


# ---------------------------------------------------------------------------
# get_or_create
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetOrCreate:
    def test_returns_existing_id_without_creating(self) -> None:
        client = _client_returning(_exists_response("DcimDevice", "existing-id-123"))

        obj_id = populate_sot.get_or_create(
            client, BASE_URL, "DcimDevice", "name", "spine01", {"name": {"value": "spine01"}}
        )

        assert obj_id == "existing-id-123"
        assert client.post.call_count == 1

    def test_creates_when_missing(self) -> None:
        client = _client_returning(
            _not_found_response("DcimDevice"),
            _create_response("DcimDevice", "new-id-456"),
        )

        obj_id = populate_sot.get_or_create(
            client, BASE_URL, "DcimDevice", "name", "leaf09", {"name": {"value": "leaf09"}}
        )

        assert obj_id == "new-id-456"
        assert client.post.call_count == 2
        _, kwargs = client.post.call_args
        assert kwargs["json"]["variables"] == {"data": {"name": {"value": "leaf09"}}}

    def test_string_lookup_value_is_quoted_in_query(self) -> None:
        client = _client_returning(_exists_response("DcimDevice", "id-1"))

        populate_sot.get_or_create(client, BASE_URL, "DcimDevice", "name", "spine01", {})

        _, kwargs = client.post.call_args
        assert 'name__value: "spine01"' in kwargs["json"]["query"]

    def test_int_lookup_value_is_not_quoted_in_query(self) -> None:
        """BigInt lookups (e.g. ASN) must be rendered unquoted."""
        client = _client_returning(_exists_response("RoutingAutonomousSystem", "id-1"))

        populate_sot.get_or_create(client, BASE_URL, "RoutingAutonomousSystem", "asn", 65000, {})

        _, kwargs = client.post.call_args
        assert "asn__value: 65000" in kwargs["json"]["query"]
        assert '"65000"' not in kwargs["json"]["query"]

    def test_raises_when_create_not_ok(self) -> None:
        client = _client_returning(
            _not_found_response("DcimDevice"),
            {"data": {"DcimDeviceCreate": {"ok": False}}},
        )

        with pytest.raises(RuntimeError, match="Failed to create"):
            populate_sot.get_or_create(client, BASE_URL, "DcimDevice", "name", "leaf09", {})


# ---------------------------------------------------------------------------
# populate_* functions (get_or_create mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPopulateFunctions:
    SEED: ClassVar[dict] = {
        "manufacturer": {"name": "Nokia", "description": "Nokia Corp"},
        "location": {"name": "lab", "shortname": "LAB", "description": "Lab site"},
        "platform": {
            "name": "SR Linux",
            "description": "Nokia SR Linux",
            "nornir_platform": "srl",
            "napalm_driver": "srl",
            "containerlab_os": "nokia_srlinux",
            "ansible_network_os": "nokia.srlinux.srlinux",
            "netmiko_device_type": "nokia_srl",
        },
        "device_types": [
            {"name": "7220 IXR-D2", "description": "Leaf", "part_number": "D2"},
            {"name": "7220 IXR-D3", "description": "Spine", "part_number": "D3"},
        ],
        "autonomous_systems": [
            {"asn": 65000, "name": "AS65000", "description": "Spines"},
            {"asn": 65001, "name": "AS65001", "description": "leaf01"},
        ],
        "vrfs": [{"name": "default", "description": "Default VRF"}],
        "devices": [
            {
                "name": "spine01",
                "description": "Spine switch",
                "status": "active",
                "role": "spine",
                "management_ip": "172.20.20.3/24",
                "lab_node_name": "clab-spine01",
                "device_type": "7220 IXR-D3",
                "asn": 65000,
            }
        ],
    }

    def _patch_get_or_create(self, return_value: str = "obj-id"):
        return patch.object(populate_sot, "get_or_create", return_value=return_value)

    def test_populate_manufacturer(self) -> None:
        with self._patch_get_or_create("mfg-id") as goc:
            assert populate_sot.populate_manufacturer(Mock(), BASE_URL, self.SEED) == "mfg-id"

        args = goc.call_args[0]
        assert args[2:5] == ("OrganizationManufacturer", "name", "Nokia")

    def test_populate_location(self) -> None:
        with self._patch_get_or_create("loc-id") as goc:
            assert populate_sot.populate_location(Mock(), BASE_URL, self.SEED) == "loc-id"

        args = goc.call_args[0]
        assert args[2:5] == ("LocationSite", "name", "lab")

    def test_populate_platform_links_manufacturer(self) -> None:
        with self._patch_get_or_create("plat-id") as goc:
            result = populate_sot.populate_platform(Mock(), BASE_URL, self.SEED, "mfg-id")

        assert result == "plat-id"
        create_data = goc.call_args[0][5]
        assert create_data["manufacturer"] == {"id": "mfg-id"}

    def test_populate_device_types_returns_name_to_id_mapping(self) -> None:
        with self._patch_get_or_create("dt-id") as goc:
            dt_ids = populate_sot.populate_device_types(Mock(), BASE_URL, self.SEED, "mfg-id", "plat-id")

        assert dt_ids == {"7220 IXR-D2": "dt-id", "7220 IXR-D3": "dt-id"}
        assert goc.call_count == 2

    def test_populate_autonomous_systems_keyed_by_asn(self) -> None:
        with self._patch_get_or_create("as-id") as goc:
            as_ids = populate_sot.populate_autonomous_systems(Mock(), BASE_URL, self.SEED, "org-id")

        assert as_ids == {65000: "as-id", 65001: "as-id"}
        # ASN lookups go through the integer (unquoted BigInt) path
        assert goc.call_args[0][3] == "asn"
        assert isinstance(goc.call_args[0][4], int)

    def test_populate_namespace_uses_default(self) -> None:
        with self._patch_get_or_create("ns-id") as goc:
            assert populate_sot.populate_namespace(Mock(), BASE_URL) == "ns-id"

        args = goc.call_args[0]
        assert args[2:5] == ("IpamNamespace", "name", "default")

    def test_populate_vrfs_links_namespace(self) -> None:
        with self._patch_get_or_create("vrf-id") as goc:
            vrf_ids = populate_sot.populate_vrfs(Mock(), BASE_URL, self.SEED, "ns-id")

        assert vrf_ids == {"default": "vrf-id"}
        assert goc.call_args[0][5]["namespace"] == {"id": "ns-id"}

    def test_populate_vrfs_handles_missing_key(self) -> None:
        with self._patch_get_or_create() as goc:
            assert populate_sot.populate_vrfs(Mock(), BASE_URL, {}, "ns-id") == {}

        goc.assert_not_called()

    def test_populate_devices_links_known_device_type_and_asn(self) -> None:
        with self._patch_get_or_create("dev-id") as goc:
            device_ids = populate_sot.populate_devices(
                Mock(),
                BASE_URL,
                self.SEED,
                location_id="loc-id",
                platform_id="plat-id",
                dt_ids={"7220 IXR-D3": "dt-id"},
                as_ids={65000: "as-id"},
            )

        assert device_ids == {"spine01": "dev-id"}
        create_data = goc.call_args[0][5]
        assert create_data["device_type"] == {"id": "dt-id"}
        assert create_data["asn"] == {"id": "as-id"}

    def test_populate_devices_skips_unknown_device_type_and_asn(self) -> None:
        with self._patch_get_or_create("dev-id") as goc:
            populate_sot.populate_devices(Mock(), BASE_URL, self.SEED, "loc-id", "plat-id", dt_ids={}, as_ids={})

        create_data = goc.call_args[0][5]
        assert "device_type" not in create_data
        assert "asn" not in create_data


# ---------------------------------------------------------------------------
# populate_ip_addresses / populate_interfaces / populate_bgp_sessions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPopulateIPAddresses:
    SEED: ClassVar[dict] = {
        "interfaces": [
            {"device": "spine01", "name": "ethernet-1/1", "ip_address": "10.0.0.0/31", "description": "a"},
            {"device": "leaf01", "name": "ethernet-1/49", "ip_address": "10.0.0.1/31", "description": "b"},
            {"device": "spine01", "name": "ethernet-1/2", "ip_address": "10.0.0.0/31", "description": "dup"},
            {"device": "spine01", "name": "mgmt0"},  # no IP -> skipped
        ]
    }

    def test_creates_each_unique_ip_once(self) -> None:
        with patch.object(populate_sot, "get_or_create", return_value="ip-id") as goc:
            ip_ids = populate_sot.populate_ip_addresses(Mock(), BASE_URL, self.SEED, "ns-id")

        assert ip_ids == {"10.0.0.0/31": "ip-id", "10.0.0.1/31": "ip-id"}
        assert goc.call_count == 2  # duplicate and IP-less interfaces skipped


@pytest.mark.unit
class TestPopulateInterfaces:
    SEED: ClassVar[dict] = {
        "interfaces": [
            {
                "device": "spine01",
                "name": "ethernet-1/1",
                "description": "to leaf01",
                "mtu": 9214,
                "role": "fabric",
                "ip_address": "10.0.0.0/31",
            },
            {"device": "ghost99", "name": "ethernet-1/1"},  # unknown device -> skipped
        ]
    }
    DEVICE_IDS: ClassVar[dict] = {"spine01": "dev-spine01"}
    IP_IDS: ClassVar[dict] = {"10.0.0.0/31": "ip-1"}

    def test_existing_interface_is_not_recreated(self) -> None:
        existing = {"InterfacePhysical": {"edges": [{"node": {"id": "iface-exists"}}]}}
        with patch.object(populate_sot, "graphql", return_value=existing) as gql:
            iface_ids = populate_sot.populate_interfaces(Mock(), BASE_URL, self.SEED, self.DEVICE_IDS, self.IP_IDS)

        assert iface_ids == {"spine01:ethernet-1/1": "iface-exists"}
        assert gql.call_count == 1  # lookup only, no create mutation

    def test_missing_interface_is_created_with_relationships(self) -> None:
        responses = [
            {"InterfacePhysical": {"edges": []}},
            {"InterfacePhysicalCreate": {"ok": True, "object": {"id": "iface-new", "display_label": "x"}}},
        ]
        with patch.object(populate_sot, "graphql", side_effect=responses) as gql:
            iface_ids = populate_sot.populate_interfaces(Mock(), BASE_URL, self.SEED, self.DEVICE_IDS, self.IP_IDS)

        assert iface_ids == {"spine01:ethernet-1/1": "iface-new"}
        create_data = gql.call_args[1]["variables"]["data"]
        assert create_data["device"] == {"id": "dev-spine01"}
        assert create_data["mtu"] == {"value": 9214}
        assert create_data["role"] == {"value": "fabric"}
        assert create_data["ip_addresses"] == [{"id": "ip-1"}]

    def test_failed_create_is_skipped(self) -> None:
        responses = [
            {"InterfacePhysical": {"edges": []}},
            {"InterfacePhysicalCreate": {"ok": False}},
        ]
        with patch.object(populate_sot, "graphql", side_effect=responses):
            iface_ids = populate_sot.populate_interfaces(Mock(), BASE_URL, self.SEED, self.DEVICE_IDS, self.IP_IDS)

        assert iface_ids == {}


@pytest.mark.unit
class TestPopulateBGPSessions:
    SEED: ClassVar[dict] = {
        "bgp_sessions": [
            {
                "description": "spine01 <-> leaf01 eBGP",
                "session_type": "EXTERNAL",
                "role": "backbone",
                "local_device": "spine01",
                "local_as": 65000,
                "remote_as": 65001,
                "local_ip": "10.0.0.0/31",
                "remote_ip": "10.0.0.1/31",
            }
        ]
    }

    def test_existing_session_is_not_recreated(self) -> None:
        existing = {"RoutingBGPSession": {"edges": [{"node": {"id": "sess-1"}}]}}
        with patch.object(populate_sot, "graphql", return_value=existing) as gql:
            populate_sot.populate_bgp_sessions(
                Mock(), BASE_URL, self.SEED, {"spine01": "dev-1"}, {65000: "as-1"}, {}, {}
            )

        assert gql.call_count == 1

    def test_missing_session_is_created_with_known_relationships(self) -> None:
        responses = [
            {"RoutingBGPSession": {"edges": []}},
            {"RoutingBGPSessionCreate": {"ok": True, "object": {"id": "sess-new", "display_label": "x"}}},
        ]
        with patch.object(populate_sot, "graphql", side_effect=responses) as gql:
            populate_sot.populate_bgp_sessions(
                Mock(),
                BASE_URL,
                self.SEED,
                device_ids={"spine01": "dev-1"},
                as_ids={65000: "as-local", 65001: "as-remote"},
                ip_ids={"10.0.0.0/31": "ip-local", "10.0.0.1/31": "ip-remote"},
                vrf_ids={"default": "vrf-default"},
            )

        create_data = gql.call_args[1]["variables"]["data"]
        assert create_data["device"] == {"id": "dev-1"}
        assert create_data["local_as"] == {"id": "as-local"}
        assert create_data["remote_as"] == {"id": "as-remote"}
        assert create_data["local_ip"] == {"id": "ip-local"}
        assert create_data["remote_ip"] == {"id": "ip-remote"}
        assert create_data["vrf"] == {"id": "vrf-default"}

    def test_unknown_relationships_are_omitted(self) -> None:
        responses = [
            {"RoutingBGPSession": {"edges": []}},
            {"RoutingBGPSessionCreate": {"ok": True, "object": {"id": "sess-new", "display_label": "x"}}},
        ]
        with patch.object(populate_sot, "graphql", side_effect=responses) as gql:
            populate_sot.populate_bgp_sessions(Mock(), BASE_URL, self.SEED, {}, {}, {}, {})

        create_data = gql.call_args[1]["variables"]["data"]
        for key in ("device", "local_as", "remote_as", "local_ip", "remote_ip", "vrf"):
            assert key not in create_data


# ---------------------------------------------------------------------------
# get_project_root
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_project_root_finds_git_root() -> None:
    root = populate_sot.get_project_root()
    assert (root / ".git").exists()
