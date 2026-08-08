"""Unit tests for override-aware state validation (Issue #64).

SuzieQ is an *independent* observer of device state. During an operational
override some objects are intentionally down (the sanctioned deviation), so
validation must be override-aware: confirm the targeted objects reached
their expected state and that everything else is still healthy.
"""

from __future__ import annotations

from network_synapse.collector import override_validation as ov


class TestOverrideExpectsTargetDown:
    def test_admin_shutdown_downs_its_target(self) -> None:
        assert ov.override_expects_target_down("admin_shutdown") is True

    def test_traffic_drain_downs_its_target(self) -> None:
        assert ov.override_expects_target_down("traffic_drain") is True

    def test_maintenance_mode_downs_its_target(self) -> None:
        assert ov.override_expects_target_down("maintenance_mode") is True

    def test_emergency_bypass_does_not_down_its_target(self) -> None:
        assert ov.override_expects_target_down("emergency_bypass") is False

    def test_unknown_type_defaults_to_not_down(self) -> None:
        assert ov.override_expects_target_down("something_else") is False


class TestValidateOverrideState:
    def _bgp(self, host: str, peer: str, state: str) -> dict:
        return {"hostname": host, "peer": peer, "state": state}

    def _iface(self, host: str, ifname: str, state: str) -> dict:
        return {"hostname": host, "ifname": ifname, "state": state}

    def test_targeted_session_down_is_consistent(self) -> None:
        """admin_shutdown of a peer: observed down == sanctioned == consistent."""
        result = ov.validate_override_state(
            device="leaf01",
            override_type="admin_shutdown",
            target_bgp_peers=["10.0.0.1"],
            target_interfaces=[],
            bgp_rows=[self._bgp("leaf01", "10.0.0.1", "NotEstd")],
            interface_rows=[],
        )
        assert result.consistent is True
        assert result.verdicts[0].status == "consistent"

    def test_targeted_session_still_up_is_override_ineffective(self) -> None:
        """The sanctioned shutdown never took effect — a real finding."""
        result = ov.validate_override_state(
            device="leaf01",
            override_type="admin_shutdown",
            target_bgp_peers=["10.0.0.1"],
            target_interfaces=[],
            bgp_rows=[self._bgp("leaf01", "10.0.0.1", "Established")],
            interface_rows=[],
        )
        assert result.consistent is False
        assert result.verdicts[0].status == "override_ineffective"

    def test_untargeted_session_down_is_unexpected(self) -> None:
        """A non-target session down is collateral damage the override can't explain."""
        result = ov.validate_override_state(
            device="leaf01",
            override_type="admin_shutdown",
            target_bgp_peers=["10.0.0.1"],
            target_interfaces=[],
            bgp_rows=[
                self._bgp("leaf01", "10.0.0.1", "NotEstd"),
                self._bgp("leaf01", "10.0.0.2", "NotEstd"),
            ],
            interface_rows=[],
        )
        assert result.consistent is False
        statuses = {v.object_id: v.status for v in result.verdicts}
        assert statuses["10.0.0.1"] == "consistent"
        assert statuses["10.0.0.2"] == "unexpected_down"

    def test_untargeted_session_established_is_consistent(self) -> None:
        result = ov.validate_override_state(
            device="leaf01",
            override_type="admin_shutdown",
            target_bgp_peers=["10.0.0.1"],
            target_interfaces=[],
            bgp_rows=[
                self._bgp("leaf01", "10.0.0.1", "NotEstd"),
                self._bgp("leaf01", "10.0.0.2", "Established"),
            ],
            interface_rows=[],
        )
        assert result.consistent is True

    def test_targeted_interface_down_is_consistent(self) -> None:
        result = ov.validate_override_state(
            device="leaf01",
            override_type="traffic_drain",
            target_bgp_peers=[],
            target_interfaces=["ethernet-1/1"],
            bgp_rows=[],
            interface_rows=[self._iface("leaf01", "ethernet-1/1", "down")],
        )
        assert result.consistent is True
        assert result.verdicts[0].kind == "interface"
        assert result.verdicts[0].status == "consistent"

    def test_untargeted_interface_down_is_unexpected(self) -> None:
        result = ov.validate_override_state(
            device="leaf01",
            override_type="traffic_drain",
            target_bgp_peers=[],
            target_interfaces=["ethernet-1/1"],
            bgp_rows=[],
            interface_rows=[
                self._iface("leaf01", "ethernet-1/1", "down"),
                self._iface("leaf01", "ethernet-1/2", "down"),
            ],
        )
        assert result.consistent is False

    def test_emergency_bypass_expects_target_up(self) -> None:
        """emergency_bypass doesn't disable its target, so target-down is a finding."""
        result = ov.validate_override_state(
            device="leaf01",
            override_type="emergency_bypass",
            target_bgp_peers=["10.0.0.1"],
            target_interfaces=[],
            bgp_rows=[self._bgp("leaf01", "10.0.0.1", "NotEstd")],
            interface_rows=[],
        )
        assert result.consistent is False
        assert result.verdicts[0].status == "unexpected_down"

    def test_rows_for_other_devices_are_ignored(self) -> None:
        result = ov.validate_override_state(
            device="leaf01",
            override_type="admin_shutdown",
            target_bgp_peers=["10.0.0.1"],
            target_interfaces=[],
            bgp_rows=[
                self._bgp("leaf01", "10.0.0.1", "NotEstd"),
                self._bgp("spine01", "10.0.0.9", "NotEstd"),
            ],
            interface_rows=[],
        )
        assert [v.object_id for v in result.verdicts] == ["10.0.0.1"]
        assert result.consistent is True

    def test_state_matching_is_case_insensitive(self) -> None:
        result = ov.validate_override_state(
            device="leaf01",
            override_type="admin_shutdown",
            target_bgp_peers=[],
            target_interfaces=[],
            bgp_rows=[self._bgp("leaf01", "10.0.0.2", "ESTABLISHED")],
            interface_rows=[],
        )
        assert result.consistent is True

    def test_result_serializes_to_dict(self) -> None:
        result = ov.validate_override_state(
            device="leaf01",
            override_type="admin_shutdown",
            target_bgp_peers=["10.0.0.1"],
            target_interfaces=[],
            bgp_rows=[self._bgp("leaf01", "10.0.0.1", "NotEstd")],
            interface_rows=[],
        )
        as_dict = result.to_dict()
        assert as_dict["device"] == "leaf01"
        assert as_dict["consistent"] is True
        assert as_dict["verdicts"][0]["object_id"] == "10.0.0.1"
