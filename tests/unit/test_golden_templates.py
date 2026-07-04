"""Golden file tests for the SR Linux Jinja2 templates (Issue #93).

Each template is rendered with known, deterministic inputs and compared
byte-for-byte against a golden file in tests/golden/. Any template change
fails these tests until the golden file is deliberately regenerated with:

    uv run pytest tests/unit/test_golden_templates.py --update-golden

Regenerated golden files show up in the PR diff for review.
"""

from __future__ import annotations

import json

import pytest

from network_synapse.scripts.generate_configs import generate_bgp_config, generate_interface_config


@pytest.fixture
def golden_interface_inputs() -> dict:
    """Deterministic interface data exercising every template branch.

    - ethernet-1/1: routed interface with IP, explicit MTU and description
    - ethernet-1/2: disabled, no IP, all defaults (mtu, subinterface index)
    - loopback0: enabled with IP, default MTU
    """
    return {
        "interfaces": [
            {
                "name": "ethernet-1/1",
                "description": "spine01 to leaf01",
                "enabled": True,
                "mtu": 9100,
                "ip_address": "10.0.0.0/31",
                "subinterface_index": 0,
            },
            {
                "name": "ethernet-1/2",
                "enabled": False,
            },
            {
                "name": "loopback0",
                "description": "router-id loopback",
                "enabled": True,
                "ip_address": "192.0.2.1/32",
            },
        ]
    }


@pytest.fixture
def golden_bgp_inputs() -> dict:
    """Deterministic BGP data exercising defaults and multi-neighbor rendering.

    - session to leaf01: all fields explicit
    - session to leaf02: group and description omitted (template defaults)
    """
    return {
        "local_asn": 65000,
        "router_id": "192.0.2.1",
        "bgp_sessions": [
            {
                "remote_ip": "10.0.0.1",
                "remote_asn": 65001,
                "group": "underlay",
                "description": "spine01 to leaf01",
            },
            {
                "remote_ip": "10.0.0.3",
                "remote_asn": 65002,
            },
        ],
    }


@pytest.mark.unit
class TestGoldenTemplates:
    def test_interfaces_template_matches_golden(self, golden, golden_interface_inputs) -> None:
        rendered = generate_interface_config(golden_interface_inputs)
        golden.assert_match(rendered, "srlinux_interfaces.json")

    def test_bgp_template_matches_golden(self, golden, golden_bgp_inputs) -> None:
        rendered = generate_bgp_config(golden_bgp_inputs)
        golden.assert_match(rendered, "srlinux_bgp.json")

    def test_interfaces_golden_output_is_valid_json(self, golden_interface_inputs) -> None:
        """The golden inputs must render to parseable JSON (gNMI SET payload)."""
        parsed = json.loads(generate_interface_config(golden_interface_inputs))
        assert [i["name"] for i in parsed["interface"]] == ["ethernet-1/1", "ethernet-1/2", "loopback0"]

    def test_bgp_golden_output_is_valid_json(self, golden_bgp_inputs) -> None:
        """The golden inputs must render to parseable JSON (gNMI SET payload)."""
        parsed = json.loads(generate_bgp_config(golden_bgp_inputs))
        bgp = parsed["network-instance"][0]["protocols"]["bgp"]
        assert bgp["autonomous-system"] == 65000
        assert len(bgp["neighbor"]) == 2


@pytest.mark.unit
class TestGoldenFramework:
    """Behaviour of the golden-file comparison helper itself."""

    def test_missing_golden_file_fails_with_update_hint(self, make_golden) -> None:
        helper = make_golden(update=False)
        with pytest.raises(AssertionError, match="--update-golden"):
            helper.assert_match("content", "does_not_exist.json")

    def test_mismatch_fails_with_diff(self, make_golden) -> None:
        helper = make_golden(update=False)
        (helper.golden_dir / "sample.json").write_text("old content\n")
        with pytest.raises(AssertionError, match=r"-old content|\+new content"):
            helper.assert_match("new content\n", "sample.json")

    def test_match_passes(self, make_golden) -> None:
        helper = make_golden(update=False)
        (helper.golden_dir / "sample.json").write_text("same content\n")
        helper.assert_match("same content\n", "sample.json")

    def test_update_mode_writes_golden_file(self, make_golden) -> None:
        helper = make_golden(update=True)
        helper.assert_match("fresh content\n", "sample.json")
        assert (helper.golden_dir / "sample.json").read_text() == "fresh content\n"

    def test_update_mode_overwrites_stale_golden_file(self, make_golden) -> None:
        helper = make_golden(update=True)
        (helper.golden_dir / "sample.json").write_text("stale\n")
        helper.assert_match("fresh\n", "sample.json")
        assert (helper.golden_dir / "sample.json").read_text() == "fresh\n"
