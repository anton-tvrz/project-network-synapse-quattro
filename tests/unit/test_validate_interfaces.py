"""Unit tests for validate_interfaces activity (Issue #50).

Tests cover:
  - Interface state evaluation logic (admin-state, oper-state checks)
  - Admin-up/oper-down detection
  - Missing interface detection
  - Disabled interface handling
  - gNMI client integration via mocked pygnmi
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from network_synapse.scripts.validate_state import (
    _evaluate_interface_state,
    check_interface_state,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_gnmi_interface(
    name: str,
    admin_state: str = "enable",
    oper_state: str = "up",
    ip_prefix: str | None = None,
) -> dict:
    """Build a gNMI interface dict matching SR Linux response structure."""
    iface: dict = {"name": name, "admin-state": admin_state, "oper-state": oper_state}
    if ip_prefix:
        iface["subinterface"] = [{"index": 0, "ipv4": {"address": [{"ip-prefix": ip_prefix}]}}]
    return iface


def _make_gnmi_response(interfaces_list: list[dict]) -> dict:
    """Wrap interface list in gNMI GET response structure."""
    return {"notification": [{"update": [{"val": interfaces_list}]}]}


def _make_intended(
    name: str,
    enabled: bool = True,
    ip_address: str | None = None,
) -> dict:
    """Build an intended interface dict matching InterfaceTemplateEntry shape."""
    return {
        "name": name,
        "description": "",
        "enabled": enabled,
        "mtu": 9214,
        "subinterface_index": 0,
        "ip_address": ip_address,
    }


# ---------------------------------------------------------------------------
# _evaluate_interface_state — pure logic tests (no mocks)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateInterfaceState:
    """Test the core interface evaluation logic."""

    def test_all_interfaces_pass(self):
        gnmi_ifaces = [
            _make_gnmi_interface("ethernet-1/1", ip_prefix="10.0.0.0/31"),
            _make_gnmi_interface("ethernet-1/2", ip_prefix="10.0.0.2/31"),
            _make_gnmi_interface("loopback0", ip_prefix="10.1.0.1/32"),
        ]
        intended = [
            _make_intended("ethernet-1/1", ip_address="10.0.0.0/31"),
            _make_intended("ethernet-1/2", ip_address="10.0.0.2/31"),
            _make_intended("loopback0", ip_address="10.1.0.1/32"),
        ]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is True
        assert len(result["details"]) == 3
        assert all(d["status"] == "pass" for d in result["details"])

    def test_admin_up_oper_down(self):
        gnmi_ifaces = [
            _make_gnmi_interface("ethernet-1/1", admin_state="enable", oper_state="down"),
            _make_gnmi_interface("ethernet-1/2"),
        ]
        intended = [
            _make_intended("ethernet-1/1"),
            _make_intended("ethernet-1/2"),
        ]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is False
        fail_detail = next((d for d in result["details"] if d["name"] == "ethernet-1/1"), None)
        assert fail_detail is not None, "ethernet-1/1 not found in details"
        assert fail_detail["status"] == "fail"
        assert "admin-up but oper-down" in fail_detail["reason"]
        # The healthy interface should still pass
        pass_detail = next((d for d in result["details"] if d["name"] == "ethernet-1/2"), None)
        assert pass_detail is not None, "ethernet-1/2 not found in details"
        assert pass_detail["status"] == "pass"

    def test_missing_interface(self):
        gnmi_ifaces = [
            _make_gnmi_interface("ethernet-1/1"),
        ]
        intended = [
            _make_intended("ethernet-1/1"),
            _make_intended("ethernet-1/99"),
        ]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is False
        fail_detail = next((d for d in result["details"] if d["name"] == "ethernet-1/99"), None)
        assert fail_detail is not None, "ethernet-1/99 not found in details"
        assert fail_detail["status"] == "fail"
        assert "not found" in fail_detail["reason"]

    def test_disabled_interface_passes(self):
        gnmi_ifaces = [
            _make_gnmi_interface("ethernet-1/1", admin_state="disable", oper_state="down"),
        ]
        intended = [
            _make_intended("ethernet-1/1", enabled=False),
        ]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is True
        assert result["details"][0]["status"] == "pass"

    def test_should_be_disabled_but_enabled(self):
        gnmi_ifaces = [
            _make_gnmi_interface("ethernet-1/1", admin_state="enable", oper_state="up"),
        ]
        intended = [
            _make_intended("ethernet-1/1", enabled=False),
        ]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is False
        assert "expected disable" in result["details"][0]["reason"]

    def test_empty_intended_passes(self):
        gnmi_ifaces = [_make_gnmi_interface("ethernet-1/1")]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, [])

        assert result["passed"] is True
        assert result["details"] == []

    def test_dict_format_gnmi_response(self):
        """gNMI response as dict-of-dicts (defensive handling)."""
        gnmi_ifaces = {
            "ethernet-1/1": _make_gnmi_interface("ethernet-1/1"),
        }
        intended = [_make_intended("ethernet-1/1")]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is True

    def test_dict_format_without_name_key(self):
        """gNMI dict response where values omit the 'name' field — uses dict key."""
        gnmi_ifaces = {
            "ethernet-1/1": {"admin-state": "enable", "oper-state": "up"},
        }
        intended = [_make_intended("ethernet-1/1")]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is True

    def test_malformed_intended_entry_fails(self):
        """Malformed intended entries (missing name) should fail, not be skipped."""
        gnmi_ifaces = [_make_gnmi_interface("ethernet-1/1")]
        intended = [{"enabled": True}]  # missing "name" key

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is False
        assert "missing interface name" in result["details"][0]["reason"]


# ---------------------------------------------------------------------------
# check_interface_state — mocked gNMI client
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckInterfaceState:
    """Test the gNMI-calling entry point with mocked pygnmi client."""

    @patch("network_synapse.scripts.validate_state.gNMIclient")
    def test_successful_validation(self, mock_gnmi_cls):
        gnmi_ifaces = [
            _make_gnmi_interface("ethernet-1/1", ip_prefix="10.0.0.0/31"),
            _make_gnmi_interface("loopback0", ip_prefix="10.1.0.1/32"),
        ]
        mock_gc = MagicMock()
        mock_gc.get.return_value = _make_gnmi_response(gnmi_ifaces)
        mock_gnmi_cls.return_value.__enter__ = MagicMock(return_value=mock_gc)
        mock_gnmi_cls.return_value.__exit__ = MagicMock(return_value=False)

        intended = [
            _make_intended("ethernet-1/1", ip_address="10.0.0.0/31"),
            _make_intended("loopback0", ip_address="10.1.0.1/32"),
        ]

        result = check_interface_state("172.20.20.3", intended)

        assert result["passed"] is True
        mock_gc.get.assert_called_once_with(path=["/interface[name=*]"], datatype="state")

    @patch("network_synapse.scripts.validate_state.gNMIclient")
    def test_gnmi_connection_failure(self, mock_gnmi_cls):
        mock_gnmi_cls.return_value.__enter__ = MagicMock(side_effect=ConnectionError("Device unreachable"))
        mock_gnmi_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = check_interface_state("172.20.20.3", [_make_intended("ethernet-1/1")])

        assert result["passed"] is False
        assert "connection error" in result["details"][0]["reason"].lower()

    @patch("network_synapse.scripts.validate_state.gNMIclient")
    def test_no_state_data(self, mock_gnmi_cls):
        mock_gc = MagicMock()
        mock_gc.get.return_value = {"notification": [{"update": []}]}
        mock_gnmi_cls.return_value.__enter__ = MagicMock(return_value=mock_gc)
        mock_gnmi_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = check_interface_state("172.20.20.3", [_make_intended("ethernet-1/1")])

        assert result["passed"] is False
        assert "No interface state data" in result["details"][0]["reason"]
