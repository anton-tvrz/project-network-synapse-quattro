"""Unit tests for config generation pipeline (Issue #12).

Tests cover:
  - Pydantic model construction and validation
  - Data transformation (GraphQL response -> template variables)
  - CIDR stripping for BGP peer-address vs preservation for interface ip-prefix
  - Router-id derivation from loopback0
  - Jinja2 template rendering produces valid SR Linux JSON
  - GraphQL response parsing
  - CLI file output
  - JSON validation helper
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from network_synapse.infrahub.client import (
    DeviceNotFoundError,
    InfrahubConfigClient,
)
from network_synapse.infrahub.models import (
    BGPSessionData,
    BGPTemplateVars,
    DeviceConfig,
    DeviceData,
    InterfaceData,
    _strip_cidr,
)
from network_synapse.scripts.generate_configs import (
    generate_bgp_config,
    generate_interface_config,
    validate_json_output,
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPydanticModels:
    """Test Pydantic model construction and defaults."""

    def test_device_data_required_fields(self):
        device = DeviceData(name="spine01", asn=65000)
        assert device.name == "spine01"
        assert device.asn == 65000
        assert device.status == "active"
        assert device.router_id == ""

    def test_interface_data_defaults(self):
        iface = InterfaceData(name="ethernet-1/1")
        assert iface.mtu == 9214
        assert iface.enabled is True
        assert iface.role == ""
        assert iface.ip_address is None

    def test_bgp_session_data_required_fields(self):
        session = BGPSessionData(
            local_asn=65000,
            remote_asn=65001,
            local_ip="10.0.0.0/31",
            remote_ip="10.0.0.1/31",
        )
        assert session.session_type == "EXTERNAL"
        assert session.peer_group == "underlay"

    def test_device_config_aggregation(self, spine01_device_config):
        assert spine01_device_config.device.name == "spine01"
        assert len(spine01_device_config.interfaces) == 5
        assert len(spine01_device_config.bgp_sessions) == 4


# ---------------------------------------------------------------------------
# CIDR handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCIDRHandling:
    """Test IP address CIDR stripping logic."""

    def test_strip_cidr_with_prefix(self):
        assert _strip_cidr("10.0.0.1/31") == "10.0.0.1"

    def test_strip_cidr_with_host_mask(self):
        assert _strip_cidr("10.1.0.1/32") == "10.1.0.1"

    def test_strip_cidr_bare_ip(self):
        assert _strip_cidr("10.0.0.1") == "10.0.0.1"


# ---------------------------------------------------------------------------
# Data transformation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDataTransformation:
    """Test DeviceConfig -> template variable transformation."""

    def test_bgp_template_vars_strips_cidr(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        for session in bgp_vars.bgp_sessions:
            assert "/" not in session.remote_ip, f"CIDR not stripped from remote_ip: {session.remote_ip}"

    def test_bgp_template_vars_has_all_sessions(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        assert len(bgp_vars.bgp_sessions) == 4

    def test_bgp_template_vars_local_asn(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        assert bgp_vars.local_asn == 65000

    def test_bgp_template_vars_router_id(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        assert bgp_vars.router_id == "10.1.0.1"

    def test_bgp_template_vars_defaults(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        assert bgp_vars.network_instance == "default"
        assert bgp_vars.group_name == "underlay"
        assert bgp_vars.export_policy == "export-all"
        assert bgp_vars.import_policy == "import-all"

    def test_interface_template_vars_keeps_cidr(self, spine01_device_config):
        iface_vars = spine01_device_config.to_interface_template_vars()
        for iface in iface_vars.interfaces:
            if iface.ip_address:
                assert "/" in iface.ip_address, f"CIDR missing from ip_address: {iface.ip_address}"

    def test_interface_template_vars_filters_by_role(self, spine01_device_config):
        """Should include fabric + loopback, exclude management."""
        iface_vars = spine01_device_config.to_interface_template_vars()
        # spine01 has 4 fabric + 1 loopback = 5 interfaces (no mgmt in seed data)
        assert len(iface_vars.interfaces) == 5

    def test_interface_template_vars_management_excluded(self):
        """Management interfaces should be filtered out."""
        config = DeviceConfig(
            device=DeviceData(name="test", asn=65000, router_id="1.1.1.1"),
            interfaces=[
                InterfaceData(name="mgmt0", role="management", ip_address="172.20.20.3/24"),
                InterfaceData(name="ethernet-1/1", role="fabric", ip_address="10.0.0.0/31"),
            ],
            bgp_sessions=[],
        )
        iface_vars = config.to_interface_template_vars()
        assert len(iface_vars.interfaces) == 1
        assert iface_vars.interfaces[0].name == "ethernet-1/1"


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTemplateRendering:
    """Test Jinja2 template rendering produces valid SR Linux JSON."""

    def test_bgp_config_renders_valid_json(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        rendered = generate_bgp_config(bgp_vars.model_dump())
        parsed = json.loads(rendered)
        assert "network-instance" in parsed

    def test_interface_config_renders_valid_json(self, spine01_device_config):
        iface_vars = spine01_device_config.to_interface_template_vars()
        rendered = generate_interface_config(iface_vars.model_dump())
        parsed = json.loads(rendered)
        assert "interface" in parsed

    def test_bgp_config_has_correct_structure(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        rendered = generate_bgp_config(bgp_vars.model_dump())
        parsed = json.loads(rendered)

        ni = parsed["network-instance"][0]
        assert ni["name"] == "default"
        bgp = ni["protocols"]["bgp"]
        assert bgp["autonomous-system"] == 65000
        assert bgp["router-id"] == "10.1.0.1"
        assert len(bgp["group"]) == 1
        assert bgp["group"][0]["group-name"] == "underlay"

    def test_bgp_neighbor_count_matches_sessions(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        rendered = generate_bgp_config(bgp_vars.model_dump())
        parsed = json.loads(rendered)

        neighbors = parsed["network-instance"][0]["protocols"]["bgp"]["neighbor"]
        assert len(neighbors) == 4

    def test_bgp_neighbor_has_bare_ip(self, spine01_device_config):
        bgp_vars = spine01_device_config.to_bgp_template_vars()
        rendered = generate_bgp_config(bgp_vars.model_dump())
        parsed = json.loads(rendered)

        neighbors = parsed["network-instance"][0]["protocols"]["bgp"]["neighbor"]
        for neighbor in neighbors:
            assert "/" not in neighbor["peer-address"]

    def test_interface_config_has_correct_structure(self, spine01_device_config):
        iface_vars = spine01_device_config.to_interface_template_vars()
        rendered = generate_interface_config(iface_vars.model_dump())
        parsed = json.loads(rendered)

        interfaces = parsed["interface"]
        assert len(interfaces) == 5
        assert interfaces[0]["name"] == "ethernet-1/1"
        assert interfaces[0]["admin-state"] == "enable"
        assert interfaces[0]["mtu"] == 9214

    def test_interface_ip_has_cidr(self, spine01_device_config):
        iface_vars = spine01_device_config.to_interface_template_vars()
        rendered = generate_interface_config(iface_vars.model_dump())
        parsed = json.loads(rendered)

        first_iface = parsed["interface"][0]
        ip_prefix = first_iface["subinterface"][0]["ipv4"]["address"][0]["ip-prefix"]
        assert "/" in ip_prefix  # Must have CIDR notation

    def test_empty_bgp_sessions_renders_valid_json(self):
        bgp_vars = BGPTemplateVars(
            local_asn=65000,
            router_id="10.1.0.1",
            bgp_sessions=[],
        )
        rendered = generate_bgp_config(bgp_vars.model_dump())
        parsed = json.loads(rendered)
        neighbors = parsed["network-instance"][0]["protocols"]["bgp"]["neighbor"]
        assert neighbors == []


# ---------------------------------------------------------------------------
# GraphQL response parsing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGraphQLResponseParsing:
    """Test parsing Infrahub GraphQL responses into Pydantic models."""

    def test_parse_device_response(self, mock_infrahub_device_response):
        """Parse raw GraphQL device response into DeviceData."""
        edges = mock_infrahub_device_response["DcimDevice"]["edges"]
        node = edges[0]["node"]
        asn_node = node["asn"]["node"]

        device = DeviceData(
            id=node["id"],
            name=node["name"]["value"],
            description=node["description"]["value"],
            management_ip=node["management_ip"]["value"],
            role=node["role"]["value"],
            asn=asn_node["asn"]["value"],
        )
        assert device.name == "spine01"
        assert device.asn == 65000

    def test_parse_interfaces_response(self, mock_infrahub_interfaces_response):
        """Parse raw GraphQL interfaces response into InterfaceData list."""
        edges = mock_infrahub_interfaces_response["InterfacePhysical"]["edges"]
        interfaces = []
        for edge in edges:
            node = edge["node"]
            ip_edges = node["ip_addresses"]["edges"]
            ip_address = ip_edges[0]["node"]["address"]["value"] if ip_edges else None
            interfaces.append(
                InterfaceData(
                    name=node["name"]["value"],
                    description=node["description"]["value"],
                    mtu=node["mtu"]["value"],
                    role=node["role"]["value"],
                    ip_address=ip_address,
                )
            )
        assert len(interfaces) == 2
        assert interfaces[0].name == "ethernet-1/1"
        assert interfaces[1].name == "loopback0"
        assert interfaces[1].ip_address == "10.1.0.1/32"

    def test_parse_bgp_sessions_response(self, mock_infrahub_bgp_sessions_response):
        """Parse raw GraphQL BGP sessions response into BGPSessionData list."""
        edges = mock_infrahub_bgp_sessions_response["RoutingBGPSession"]["edges"]
        node = edges[0]["node"]

        session = BGPSessionData(
            description=node["description"]["value"],
            local_asn=node["local_as"]["node"]["asn"]["value"],
            remote_asn=node["remote_as"]["node"]["asn"]["value"],
            local_ip=node["local_ip"]["node"]["address"]["value"],
            remote_ip=node["remote_ip"]["node"]["address"]["value"],
            peer_group=node["peer_group"]["node"]["name"]["value"],
        )
        assert session.local_asn == 65000
        assert session.remote_asn == 65001
        assert session.remote_ip == "10.0.0.1/31"

    def test_device_not_found_raises(self):
        """DeviceNotFoundError should contain the hostname."""
        err = DeviceNotFoundError("missing-device")
        assert err.hostname == "missing-device"
        assert "missing-device" in str(err)


# ---------------------------------------------------------------------------
# InfrahubConfigClient (with mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInfrahubConfigClient:
    """Test client methods with mocked GraphQL responses."""

    def test_get_device_parses_response(self, mock_infrahub_device_response):
        client = InfrahubConfigClient(url="http://test:8000", token="fake")
        with patch.object(client, "_graphql", return_value=mock_infrahub_device_response):
            device = client.get_device("spine01")
        assert device.name == "spine01"
        assert device.asn == 65000
        assert device.id == "device-spine01-id"

    def test_get_device_not_found_raises(self):
        client = InfrahubConfigClient(url="http://test:8000", token="fake")
        empty_response = {"DcimDevice": {"edges": []}}
        with patch.object(client, "_graphql", return_value=empty_response), pytest.raises(DeviceNotFoundError):
            client.get_device("nonexistent")

    def test_get_device_interfaces_parses(self, mock_infrahub_interfaces_response):
        client = InfrahubConfigClient(url="http://test:8000", token="fake")
        with patch.object(client, "_graphql", return_value=mock_infrahub_interfaces_response):
            interfaces = client.get_device_interfaces("device-spine01-id")
        assert len(interfaces) == 2
        assert interfaces[0].name == "ethernet-1/1"
        assert interfaces[0].ip_address == "10.0.0.0/31"

    def test_get_device_bgp_sessions_parses(self, mock_infrahub_bgp_sessions_response):
        client = InfrahubConfigClient(url="http://test:8000", token="fake")
        with patch.object(client, "_graphql", return_value=mock_infrahub_bgp_sessions_response):
            sessions = client.get_device_bgp_sessions("device-spine01-id")
        assert len(sessions) == 1
        assert sessions[0].remote_asn == 65001

    def test_get_all_device_hostnames(self):
        client = InfrahubConfigClient(url="http://test:8000", token="fake")
        response = {
            "DcimDevice": {
                "edges": [
                    {"node": {"name": {"value": "spine01"}}},
                    {"node": {"name": {"value": "leaf01"}}},
                    {"node": {"name": {"value": "leaf02"}}},
                ]
            }
        }
        with patch.object(client, "_graphql", return_value=response):
            hostnames = client.get_all_device_hostnames()
        assert hostnames == ["spine01", "leaf01", "leaf02"]


# ---------------------------------------------------------------------------
# JSON validation helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJSONValidation:
    """Test the validate_json_output helper."""

    def test_valid_json_is_reformatted(self):
        raw = '{"key": "value"}'
        result = validate_json_output(raw, "test")
        assert result == '{\n  "key": "value"\n}'

    def test_invalid_json_returns_original(self, capsys):
        raw = "not json {{"
        result = validate_json_output(raw, "test")
        assert result == raw
        captured = capsys.readouterr()
        assert "WARNING" in captured.err


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileOutput:
    """Test config file writing."""

    def test_output_directory_structure(self, spine01_device_config, tmp_path):
        """Verify generate_for_device writes correct directory structure."""
        from network_synapse.scripts.generate_configs import generate_for_device

        # Create a mock client that returns our fixture
        mock_client = MagicMock(spec=InfrahubConfigClient)
        mock_client.get_device_config.return_value = spine01_device_config

        result = generate_for_device(mock_client, "spine01", tmp_path, dry_run=False)

        assert result is True
        assert (tmp_path / "spine01" / "bgp.json").exists()
        assert (tmp_path / "spine01" / "interfaces.json").exists()

    def test_output_files_are_valid_json(self, spine01_device_config, tmp_path):
        """Verify written files contain valid JSON."""
        from network_synapse.scripts.generate_configs import generate_for_device

        mock_client = MagicMock(spec=InfrahubConfigClient)
        mock_client.get_device_config.return_value = spine01_device_config

        generate_for_device(mock_client, "spine01", tmp_path, dry_run=False)

        bgp_content = (tmp_path / "spine01" / "bgp.json").read_text()
        iface_content = (tmp_path / "spine01" / "interfaces.json").read_text()

        bgp_parsed = json.loads(bgp_content)
        iface_parsed = json.loads(iface_content)

        assert "network-instance" in bgp_parsed
        assert "interface" in iface_parsed

    def test_dry_run_does_not_write_files(self, spine01_device_config, tmp_path):
        """Dry run should not create any files."""
        from network_synapse.scripts.generate_configs import generate_for_device

        mock_client = MagicMock(spec=InfrahubConfigClient)
        mock_client.get_device_config.return_value = spine01_device_config

        result = generate_for_device(mock_client, "spine01", tmp_path, dry_run=True)

        assert result is True
        assert not (tmp_path / "spine01").exists()
