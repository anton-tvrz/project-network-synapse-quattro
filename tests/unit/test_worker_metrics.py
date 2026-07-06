"""Unit tests for the worker Prometheus metrics (Issue #62).

Covers the intent lifecycle metric contract, the emissions wired into the
deployment and Infrahub activities, and the /metrics server startup in the
worker entry point.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from synapse_workers import metrics, worker
from synapse_workers.activities import config_deployment_activities as cda
from synapse_workers.activities import infrahub_activities

# Metric name -> prometheus type, per Issue #62
EXPECTED_METRICS = {
    "intent_connectivity": "counter",
    "intent_provisioning_duration_seconds": "histogram",
    "intent_orphaned_rules_count": "gauge",
    "intent_lineage_completeness_ratio": "gauge",
    "intent_binding_failures": "counter",
    "intent_decommission_age_days": "histogram",
}


def _sample(name: str, labels: dict[str, str] | None = None) -> float | None:
    return metrics.REGISTRY.get_sample_value(name, labels or {})


@pytest.mark.unit
class TestMetricContract:
    """All six Issue #62 metrics exist in the worker registry with correct types."""

    def test_all_six_metrics_registered_with_expected_types(self) -> None:
        """The registry exposes every metric from the issue spec."""
        families = {f.name: f.type for f in metrics.REGISTRY.collect()}
        for name, metric_type in EXPECTED_METRICS.items():
            assert families.get(name) == metric_type, f"{name}: expected {metric_type}, got {families.get(name)}"

    def test_metrics_use_dedicated_registry_not_global_default(self) -> None:
        """Worker metrics live in their own registry so tests and imports stay isolated."""
        from prometheus_client import REGISTRY as GLOBAL_REGISTRY

        assert metrics.REGISTRY is not GLOBAL_REGISTRY


@pytest.mark.unit
class TestDeploymentInstrumentation:
    """deploy_config / rollback_config emit connectivity and provisioning metrics."""

    def test_successful_deploy_counts_deployed_and_observes_duration(self) -> None:
        """A successful deployment increments status=deployed and records duration."""
        before_count = _sample("intent_connectivity_total", {"status": "deployed"}) or 0
        before_hist = _sample("intent_provisioning_duration_seconds_count") or 0

        with patch.object(cda, "deploy_config_via_gnmi", new=AsyncMock(return_value=True)):
            result = asyncio.run(cda.deploy_config("leaf01", "172.20.20.2", "{}"))

        assert result is True
        assert _sample("intent_connectivity_total", {"status": "deployed"}) == before_count + 1
        assert _sample("intent_provisioning_duration_seconds_count") == before_hist + 1

    def test_failed_deploy_counts_failed_and_raises(self) -> None:
        """A failed deployment increments status=failed and still raises."""
        before = _sample("intent_connectivity_total", {"status": "failed"}) or 0

        with (
            patch.object(cda, "deploy_config_via_gnmi", new=AsyncMock(return_value=False)),
            pytest.raises(RuntimeError, match="deployment failed"),
        ):
            asyncio.run(cda.deploy_config("leaf01", "172.20.20.2", "{}"))

        assert _sample("intent_connectivity_total", {"status": "failed"}) == before + 1

    def test_successful_rollback_counts_rolled_back(self) -> None:
        """A successful rollback increments status=rolled_back."""
        before = _sample("intent_connectivity_total", {"status": "rolled_back"}) or 0

        with patch.object(cda, "deploy_config_via_gnmi", new=AsyncMock(return_value=True)):
            asyncio.run(cda.rollback_config("leaf01", "172.20.20.2", "{}"))

        assert _sample("intent_connectivity_total", {"status": "rolled_back"}) == before + 1

    def test_failed_rollback_counts_rollback_failed_and_raises(self) -> None:
        """A failed rollback increments status=rollback_failed and still raises."""
        before = _sample("intent_connectivity_total", {"status": "rollback_failed"}) or 0

        with (
            patch.object(cda, "deploy_config_via_gnmi", new=AsyncMock(return_value=False)),
            pytest.raises(RuntimeError, match="Rollback failed"),
        ):
            asyncio.run(cda.rollback_config("leaf01", "172.20.20.2", "{}"))

        assert _sample("intent_connectivity_total", {"status": "rollback_failed"}) == before + 1


@pytest.mark.unit
class TestBindingFailureInstrumentation:
    """fetch_device_config failures count as intent binding failures."""

    def test_fetch_failure_increments_binding_failures_and_reraises(self) -> None:
        """An Infrahub lookup failure increments the counter and propagates."""
        before = _sample("intent_binding_failures_total") or 0
        failing_client = MagicMock()
        failing_client.get_device_config.side_effect = RuntimeError("device not found")

        with (
            patch.object(infrahub_activities, "InfrahubConfigClient", return_value=failing_client),
            pytest.raises(RuntimeError, match="device not found"),
        ):
            asyncio.run(infrahub_activities.fetch_device_config("ghost01"))

        assert _sample("intent_binding_failures_total") == before + 1


@pytest.mark.unit
class TestMetricsServer:
    """The worker exposes /metrics on startup."""

    def test_start_metrics_server_binds_worker_registry(self) -> None:
        """start_metrics_server serves the dedicated registry on the given port."""
        with patch.object(metrics, "start_http_server") as mock_start:
            metrics.start_metrics_server(9464)
        mock_start.assert_called_once_with(9464, registry=metrics.REGISTRY)

    def test_worker_main_starts_metrics_server_on_default_port(self) -> None:
        """worker.main brings up /metrics on 9464 unless overridden."""
        with (
            patch.object(worker.Client, "connect", new=AsyncMock()),
            patch.object(worker, "Worker") as mock_worker_cls,
            patch.object(worker, "start_metrics_server") as mock_metrics,
        ):
            mock_worker_cls.return_value.run = AsyncMock()
            asyncio.run(worker.main())
        mock_metrics.assert_called_once_with(9464)

    def test_worker_main_skips_metrics_server_when_port_is_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WORKER_METRICS_PORT=0 disables the metrics endpoint."""
        monkeypatch.setenv("WORKER_METRICS_PORT", "0")
        with (
            patch.object(worker.Client, "connect", new=AsyncMock()),
            patch.object(worker, "Worker") as mock_worker_cls,
            patch.object(worker, "start_metrics_server") as mock_metrics,
        ):
            mock_worker_cls.return_value.run = AsyncMock()
            asyncio.run(worker.main())
        mock_metrics.assert_not_called()
