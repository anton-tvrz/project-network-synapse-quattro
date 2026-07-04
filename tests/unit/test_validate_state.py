"""Unit tests for BGP state validation in validate_state.py (Issue #141).

Tests cover:
  - gNMI response value extraction (_extract_gnmi_val)
  - BGP neighbor evaluation (_evaluate_bgp_neighbors) for list/dict formats,
    non-established sessions, and malformed data
  - check_bgp_summary via mocked pygnmi client
  - Remaining _evaluate_interface_state edge cases (unexpected gNMI data
    format, non-dict intended entries, admin-state mismatch)

Interface-state happy paths are covered in test_validate_interfaces.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from network_synapse.scripts.validate_state import (
    _evaluate_bgp_neighbors,
    _evaluate_interface_state,
    _extract_gnmi_val,
    check_bgp_summary,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_peer(address: str, state: str = "established") -> dict:
    return {"peer-address": address, "session-state": state}


def _make_gnmi_response(val: object) -> dict:
    return {"notification": [{"update": [{"val": val}]}]}


# ---------------------------------------------------------------------------
# _extract_gnmi_val
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractGnmiVal:
    """Test extraction of the first 'val' payload from gNMI GET responses."""

    def test_extracts_first_val(self):
        assert _extract_gnmi_val(_make_gnmi_response({"x": 1})) == {"x": 1}

    def test_empty_response_returns_none(self):
        assert _extract_gnmi_val({}) is None

    def test_update_without_val_returns_none(self):
        assert _extract_gnmi_val({"notification": [{"update": [{"path": "/x"}]}]}) is None


# ---------------------------------------------------------------------------
# _evaluate_bgp_neighbors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateBGPNeighbors:
    """Test BGP session state evaluation across response formats."""

    def test_all_established_list_passes(self):
        neighbors = [_make_peer("10.0.0.1"), _make_peer("10.0.0.3", state="ESTABLISHED")]
        assert _evaluate_bgp_neighbors("172.20.20.2", neighbors) is True

    def test_one_idle_session_fails(self):
        neighbors = [_make_peer("10.0.0.1"), _make_peer("10.0.0.3", state="idle")]
        assert _evaluate_bgp_neighbors("172.20.20.2", neighbors) is False

    def test_dict_keyed_by_peer_passes(self):
        neighbors = {
            "10.0.0.1": _make_peer("10.0.0.1"),
            "10.0.0.3": _make_peer("10.0.0.3"),
        }
        assert _evaluate_bgp_neighbors("172.20.20.2", neighbors) is True

    def test_empty_neighbors_fails(self):
        assert _evaluate_bgp_neighbors("172.20.20.2", []) is False

    def test_none_neighbors_fails(self):
        assert _evaluate_bgp_neighbors("172.20.20.2", None) is False

    def test_unexpected_format_fails(self):
        assert _evaluate_bgp_neighbors("172.20.20.2", "not-a-neighbor-block") is False

    def test_missing_session_state_fails(self):
        assert _evaluate_bgp_neighbors("172.20.20.2", [{"peer-address": "10.0.0.1"}]) is False


# ---------------------------------------------------------------------------
# check_bgp_summary — mocked gNMI client
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckBGPSummary:
    """Test the gNMI-calling BGP entry point with mocked pygnmi client."""

    @patch("network_synapse.scripts.validate_state.gNMIclient")
    def test_all_sessions_established(self, mock_gnmi_cls):
        mock_gc = MagicMock()
        mock_gc.get.return_value = _make_gnmi_response([_make_peer("10.0.0.1")])
        mock_gnmi_cls.return_value.__enter__ = MagicMock(return_value=mock_gc)
        mock_gnmi_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert check_bgp_summary("172.20.20.2") is True
        mock_gc.get.assert_called_once_with(
            path=["/network-instance[name=default]/protocols/bgp/neighbor"],
            datatype="state",
        )

    @patch("network_synapse.scripts.validate_state.gNMIclient")
    def test_session_down_fails(self, mock_gnmi_cls):
        mock_gc = MagicMock()
        mock_gc.get.return_value = _make_gnmi_response([_make_peer("10.0.0.1", state="active")])
        mock_gnmi_cls.return_value.__enter__ = MagicMock(return_value=mock_gc)
        mock_gnmi_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert check_bgp_summary("172.20.20.2") is False

    @patch("network_synapse.scripts.validate_state.gNMIclient")
    def test_no_bgp_state_data_fails(self, mock_gnmi_cls):
        mock_gc = MagicMock()
        mock_gc.get.return_value = {"notification": [{"update": []}]}
        mock_gnmi_cls.return_value.__enter__ = MagicMock(return_value=mock_gc)
        mock_gnmi_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert check_bgp_summary("172.20.20.2") is False

    @patch("network_synapse.scripts.validate_state.gNMIclient")
    def test_connection_failure_fails(self, mock_gnmi_cls):
        mock_gnmi_cls.return_value.__enter__ = MagicMock(side_effect=ConnectionError("unreachable"))
        mock_gnmi_cls.return_value.__exit__ = MagicMock(return_value=False)

        assert check_bgp_summary("172.20.20.2") is False


# ---------------------------------------------------------------------------
# _evaluate_interface_state — remaining edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateInterfaceStateEdgeCases:
    """Test interface evaluation branches not covered by test_validate_interfaces.py."""

    def test_unexpected_gnmi_data_format_fails(self):
        result = _evaluate_interface_state("172.20.20.3", "not-interface-data", [])

        assert result["passed"] is False
        assert "Unexpected data format" in result["details"][0]["reason"]

    def test_non_dict_intended_entry_fails(self):
        gnmi_ifaces = [{"name": "ethernet-1/1", "admin-state": "enable", "oper-state": "up"}]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, ["ethernet-1/1"])

        assert result["passed"] is False
        assert "malformed intended interface entry" in result["details"][0]["reason"]

    def test_admin_state_disabled_when_enable_expected_fails(self):
        gnmi_ifaces = [{"name": "ethernet-1/1", "admin-state": "disable", "oper-state": "down"}]
        intended = [{"name": "ethernet-1/1", "enabled": True}]

        result = _evaluate_interface_state("172.20.20.3", gnmi_ifaces, intended)

        assert result["passed"] is False
        assert "admin-state is disable, expected enable" in result["details"][0]["reason"]
