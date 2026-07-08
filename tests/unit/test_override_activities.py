"""Unit tests for the operational override activities and metrics (Issue #63).

Covers the override metric contract (six metrics from the issue spec) and
the emissions wired into the override activities. Metrics are emitted from
activities only — never from workflow code, which Temporal replays.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from synapse_workers import metrics
from synapse_workers.activities import override_activities as oa

# Metric name -> prometheus type, per Issue #63
EXPECTED_METRICS = {
    "override_active_count": "gauge",
    "override_auto_revert_success": "counter",
    "override_auto_revert_failure": "counter",
    "override_mean_duration_seconds": "histogram",
    "override_extension_count": "counter",
    "override_state_validation_result": "gauge",
}


def _sample(name: str, labels: dict[str, str] | None = None) -> float | None:
    return metrics.REGISTRY.get_sample_value(name, labels or {})


@pytest.mark.unit
class TestOverrideMetricContract:
    """All six Issue #63 metrics exist in the worker registry with correct types."""

    def test_all_six_metrics_registered_with_expected_types(self) -> None:
        """The registry exposes every metric from the issue spec."""
        families = {f.name: f.type for f in metrics.REGISTRY.collect()}
        for name, metric_type in EXPECTED_METRICS.items():
            assert families.get(name) == metric_type, f"{name}: expected {metric_type}, got {families.get(name)}"


@pytest.mark.unit
class TestApplyOverrideConfig:
    """apply_override_config deploys via gNMI and tracks the active gauge."""

    def test_successful_apply_increments_active_gauge(self) -> None:
        before = _sample("override_active_count") or 0

        with patch.object(oa, "deploy_config_via_gnmi", new=AsyncMock(return_value=True)):
            result = asyncio.run(oa.apply_override_config("leaf01", "172.20.20.2", "{}"))

        assert result is True
        assert _sample("override_active_count") == before + 1

    def test_failed_apply_raises_without_touching_gauge(self) -> None:
        before = _sample("override_active_count") or 0

        with (
            patch.object(oa, "deploy_config_via_gnmi", new=AsyncMock(return_value=False)),
            pytest.raises(RuntimeError, match="apply failed"),
        ):
            asyncio.run(oa.apply_override_config("leaf01", "172.20.20.2", "{}"))

        assert _sample("override_active_count") == before


@pytest.mark.unit
class TestRevertOverrideConfig:
    """revert_override_config converges to intent and records revert metrics."""

    def test_successful_revert_counts_success_and_observes_duration(self) -> None:
        before_gauge = _sample("override_active_count") or 0
        before_success = _sample("override_auto_revert_success_total") or 0
        before_hist_count = _sample("override_mean_duration_seconds_count") or 0
        before_hist_sum = _sample("override_mean_duration_seconds_sum") or 0

        with patch.object(oa, "deploy_config_via_gnmi", new=AsyncMock(return_value=True)):
            result = asyncio.run(oa.revert_override_config("leaf01", "172.20.20.2", "{}", 3600.0))

        assert result is True
        assert _sample("override_active_count") == before_gauge - 1
        assert _sample("override_auto_revert_success_total") == before_success + 1
        assert _sample("override_mean_duration_seconds_count") == before_hist_count + 1
        assert _sample("override_mean_duration_seconds_sum") == before_hist_sum + 3600.0

    def test_failed_revert_raises_and_leaves_metrics_to_the_workflow(self) -> None:
        """On failure the workflow records the outcome via record_override_revert_failure."""
        before_gauge = _sample("override_active_count") or 0
        before_failure = _sample("override_auto_revert_failure_total") or 0

        with (
            patch.object(oa, "deploy_config_via_gnmi", new=AsyncMock(return_value=False)),
            pytest.raises(RuntimeError, match="revert failed"),
        ):
            asyncio.run(oa.revert_override_config("leaf01", "172.20.20.2", "{}", 3600.0))

        assert _sample("override_active_count") == before_gauge
        assert _sample("override_auto_revert_failure_total") == before_failure


@pytest.mark.unit
class TestRecordOverrideRevertFailure:
    """record_override_revert_failure counts the failure and clears the gauge."""

    def test_records_failure_and_decrements_gauge(self) -> None:
        before_gauge = _sample("override_active_count") or 0
        before_failure = _sample("override_auto_revert_failure_total") or 0

        asyncio.run(oa.record_override_revert_failure("leaf01", "gNMI SET failed"))

        assert _sample("override_active_count") == before_gauge - 1
        assert _sample("override_auto_revert_failure_total") == before_failure + 1


@pytest.mark.unit
class TestCheckReversionSafety:
    """check_reversion_safety validates device state and sets the result gauge."""

    def test_safe_state_sets_gauge_to_one(self) -> None:
        with patch.object(oa, "check_bgp_summary", return_value=True):
            result = asyncio.run(oa.check_reversion_safety("leaf01", "172.20.20.2"))

        assert result is True
        assert _sample("override_state_validation_result", {"device": "leaf01"}) == 1

    def test_unsafe_state_sets_gauge_to_zero_without_raising(self) -> None:
        """Unsafe is a decision input for the workflow, not an activity error."""
        with patch.object(oa, "check_bgp_summary", return_value=False):
            result = asyncio.run(oa.check_reversion_safety("leaf01", "172.20.20.2"))

        assert result is False
        assert _sample("override_state_validation_result", {"device": "leaf01"}) == 0


@pytest.mark.unit
class TestRecordOverrideExtension:
    """record_override_extension counts window extensions."""

    def test_extension_increments_counter(self) -> None:
        before = _sample("override_extension_count_total") or 0

        asyncio.run(oa.record_override_extension("leaf01-drain", 7200))

        assert _sample("override_extension_count_total") == before + 1


@pytest.mark.unit
class TestUpdateOverrideStatus:
    """update_override_status delegates to the Infrahub client and always closes it."""

    def test_updates_status_via_client(self) -> None:
        client = MagicMock()
        client.update_override_status.return_value = "active"

        with patch.object(oa, "InfrahubConfigClient", return_value=client):
            asyncio.run(oa.update_override_status("leaf01-drain", "reverted"))

        client.update_override_status.assert_called_once_with("leaf01-drain", "reverted")
        client.close.assert_called_once()

    def test_client_error_propagates_and_client_still_closed(self) -> None:
        client = MagicMock()
        client.update_override_status.side_effect = RuntimeError("Infrahub unavailable")

        with (
            patch.object(oa, "InfrahubConfigClient", return_value=client),
            pytest.raises(RuntimeError, match="Infrahub unavailable"),
        ):
            asyncio.run(oa.update_override_status("leaf01-drain", "reverted"))

        client.close.assert_called_once()
