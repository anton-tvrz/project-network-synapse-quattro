"""Unit tests for the compliance posture writer (Issue #70).

Covers the derivable-metrics MVP:
  - per-device modeling completeness from Infrahub data
  - drift score between intended and running config JSON
  - fleet coverage ratio aggregation
  - InfluxDB line-protocol construction and HTTP write
  - CLI entry point (dry-run and failure exit codes)

True intent-lineage coverage replaces the completeness stand-in once the
intent schemas land in Infrahub.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from network_synapse.infrahub.models import BGPSessionData, DeviceConfig, DeviceData, InterfaceData
from network_synapse.monitoring import compliance_posture as cp


def _device_config(
    *,
    asn: int = 65000,
    router_id: str = "10.1.0.1",
    management_ip: str = "172.20.20.3/24",
    role: str = "spine",
    with_ip_interface: bool = True,
    with_bgp: bool = True,
) -> DeviceConfig:
    """Build a DeviceConfig with selectable completeness gaps."""
    device = DeviceData(
        id="dev-id",
        name="spine01",
        management_ip=management_ip,
        role=role,
        asn=asn,
        router_id=router_id,
    )
    interfaces = [
        InterfaceData(
            name="ethernet-1/1",
            description="to leaf01",
            role="fabric",
            ip_address="10.0.0.0/31" if with_ip_interface else "",
        )
    ]
    bgp_sessions = (
        [
            BGPSessionData(
                local_asn=65000,
                remote_asn=65001,
                local_ip="10.0.0.0/31",
                remote_ip="10.0.0.1/31",
                description="spine01 to leaf01",
            )
        ]
        if with_bgp
        else []
    )
    return DeviceConfig(device=device, interfaces=interfaces, bgp_sessions=bgp_sessions)


@pytest.mark.unit
class TestDeviceCompleteness:
    """Modeling completeness scoring for a single device."""

    def test_fully_modeled_device_scores_one(self, spine01_device_config: DeviceConfig) -> None:
        """A device with ASN, router-id, mgmt IP, role, routed interface, and BGP scores 1.0."""
        completeness, missing = cp.compute_device_completeness(spine01_device_config)
        assert completeness == 1.0
        assert missing == []

    def test_missing_router_id_lowers_score_and_is_reported(self) -> None:
        """A device without a router-id loses one completeness component."""
        completeness, missing = cp.compute_device_completeness(_device_config(router_id=""))
        assert 0.0 < completeness < 1.0
        assert missing == ["router_id"]

    def test_multiple_gaps_are_all_reported(self) -> None:
        """Each modeling gap appears in the missing list."""
        config = _device_config(router_id="", with_bgp=False, with_ip_interface=False)
        completeness, missing = cp.compute_device_completeness(config)
        assert set(missing) == {"router_id", "routed_interface", "bgp_sessions"}
        assert completeness == pytest.approx(1 - len(missing) / 6)


@pytest.mark.unit
class TestDriftScore:
    """Structural drift scoring between intended and running config JSON."""

    def test_identical_configs_score_zero(self) -> None:
        """Byte-identical structures have no drift."""
        payload = json.dumps({"interface": [{"name": "ethernet-1/1"}]})
        assert cp.compute_drift_score(payload, payload) == 0.0

    def test_one_differing_section_of_two_scores_half(self) -> None:
        """Drift is the fraction of differing top-level sections."""
        intended = json.dumps({"interface": [{"mtu": 9100}], "network-instance": [{"name": "default"}]})
        running = json.dumps({"interface": [{"mtu": 1500}], "network-instance": [{"name": "default"}]})
        assert cp.compute_drift_score(intended, running) == 0.5

    def test_section_missing_from_running_counts_as_drift(self) -> None:
        """A section present in intended but absent from running is drift."""
        intended = json.dumps({"interface": [], "network-instance": []})
        running = json.dumps({"interface": []})
        assert cp.compute_drift_score(intended, running) == 0.5

    def test_invalid_json_scores_max_drift(self) -> None:
        """Unparseable running config is treated as fully drifted."""
        assert cp.compute_drift_score(json.dumps({"a": 1}), "not json{") == 1.0


@pytest.mark.unit
class TestFleetAggregation:
    """Fleet-level coverage ratio."""

    def test_ratio_is_mean_of_device_completeness(self) -> None:
        """Fleet ratio averages per-device completeness."""
        postures = [
            cp.DevicePosture(device="spine01", device_group="spine", completeness=1.0, missing=[]),
            cp.DevicePosture(device="leaf01", device_group="leaf", completeness=0.5, missing=["x"]),
        ]
        assert cp.fleet_coverage_ratio(postures) == 0.75

    def test_empty_fleet_scores_zero(self) -> None:
        """No devices means no coverage."""
        assert cp.fleet_coverage_ratio([]) == 0.0


@pytest.mark.unit
class TestLineProtocol:
    """InfluxDB line-protocol construction."""

    def test_device_line_has_measurement_tags_and_fields(self) -> None:
        """Each device posture becomes one tagged line with completeness field."""
        posture = cp.DevicePosture(device="spine01", device_group="spine", completeness=1.0, missing=[])
        lines = cp.build_influx_lines([posture], environment="lab", timestamp_s=1700000000)
        device_lines = [ln for ln in lines if ln.startswith("compliance_posture,")]
        assert len(device_lines) == 1
        assert "environment=lab" in device_lines[0]
        assert "device_group=spine" in device_lines[0]
        assert "device=spine01" in device_lines[0]
        assert "completeness=1" in device_lines[0]
        assert device_lines[0].endswith(" 1700000000")

    def test_drift_score_field_included_when_present(self) -> None:
        """drift_score is written only for devices where it was computed."""
        posture = cp.DevicePosture(device="leaf01", device_group="leaf", completeness=1.0, missing=[], drift_score=0.25)
        (line,) = [
            ln
            for ln in cp.build_influx_lines([posture], environment="lab", timestamp_s=1)
            if ln.startswith("compliance_posture,")
        ]
        assert "drift_score=0.25" in line

    def test_fleet_line_carries_lineage_coverage_ratio(self) -> None:
        """A fleet-level line reports lineage_coverage_ratio for dashboards and alerts."""
        posture = cp.DevicePosture(device="spine01", device_group="spine", completeness=0.5, missing=["x"])
        lines = cp.build_influx_lines([posture], environment="lab", timestamp_s=1)
        (fleet_line,) = [ln for ln in lines if ln.startswith("compliance_posture_fleet,")]
        assert "environment=lab" in fleet_line
        assert "lineage_coverage_ratio=0.5" in fleet_line

    def test_tag_values_with_spaces_are_escaped(self) -> None:
        """Line protocol tag values must escape spaces."""
        posture = cp.DevicePosture(device="bad name", device_group="spine", completeness=1.0, missing=[])
        (line,) = [
            ln
            for ln in cp.build_influx_lines([posture], environment="lab", timestamp_s=1)
            if ln.startswith("compliance_posture,")
        ]
        assert r"device=bad\ name" in line


@pytest.mark.unit
class TestWritePosture:
    """HTTP write to the InfluxDB v2 API."""

    def test_successful_write_posts_line_protocol(self) -> None:
        """Lines are POSTed to /api/v2/write with token auth and correct params."""
        response = MagicMock(status_code=204)
        with patch.object(cp.httpx, "post", return_value=response) as mock_post:
            cp.write_posture(
                ["m,environment=lab v=1 1"],
                url="http://influxdb:8086",
                token="tok",
                org="synapse",
                bucket="compliance",
            )
        _, kwargs = mock_post.call_args
        assert mock_post.call_args[0][0] == "http://influxdb:8086/api/v2/write"
        assert kwargs["params"] == {"org": "synapse", "bucket": "compliance", "precision": "s"}
        assert kwargs["headers"]["Authorization"] == "Token tok"
        assert kwargs["content"] == "m,environment=lab v=1 1"

    def test_error_response_raises_runtime_error(self) -> None:
        """A non-2xx response fails loudly."""
        response = MagicMock(status_code=401, text="unauthorized")
        with (
            patch.object(cp.httpx, "post", return_value=response),
            pytest.raises(RuntimeError, match="401"),
        ):
            cp.write_posture(["m v=1 1"], url="http://x", token="t", org="o", bucket="b")


@pytest.mark.unit
class TestMain:
    """CLI entry point."""

    def test_dry_run_prints_lines_without_writing(self, capsys, spine01_device_config: DeviceConfig) -> None:
        """--dry-run collects posture and prints line protocol, no HTTP write."""
        client = MagicMock()
        client.list_devices.return_value = ["spine01"]
        client.get_device_config.return_value = spine01_device_config
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        with (
            patch.object(cp, "InfrahubConfigClient", return_value=client),
            patch.object(cp, "write_posture") as mock_write,
        ):
            exit_code = cp.main(["--dry-run"])
        assert exit_code == 0
        mock_write.assert_not_called()
        out = capsys.readouterr().out
        assert "compliance_posture,environment=" in out
        assert "compliance_posture_fleet," in out

    def test_write_failure_returns_nonzero(self, spine01_device_config: DeviceConfig) -> None:
        """An InfluxDB write error surfaces as exit code 1."""
        client = MagicMock()
        client.list_devices.return_value = ["spine01"]
        client.get_device_config.return_value = spine01_device_config
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=None)
        with (
            patch.object(cp, "InfrahubConfigClient", return_value=client),
            patch.object(cp, "write_posture", side_effect=RuntimeError("influx write failed: 500")),
        ):
            exit_code = cp.main([])
        assert exit_code == 1
