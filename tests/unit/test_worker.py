"""Unit tests for the Temporal worker entry point.

`worker.main()` connects to Temporal and registers all workflows and
activities on the `network-changes` task queue. These tests mock the Temporal
SDK so we can assert the registration contract without a live server.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from synapse_workers import worker
from synapse_workers.workflows.drift_remediation_workflow import DriftRemediationWorkflow
from synapse_workers.workflows.emergency_change_workflow import EmergencyChangeWorkflow
from synapse_workers.workflows.network_change_workflow import NetworkChangeWorkflow
from synapse_workers.workflows.operational_override_workflow import OperationalOverrideWorkflow


@pytest.fixture(autouse=True)
def _no_metrics_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep worker.main() from binding the real /metrics port in these tests."""
    monkeypatch.setenv("WORKER_METRICS_PORT", "0")


@pytest.mark.asyncio
async def test_main_connects_with_default_address_and_runs() -> None:
    """With no env override, connect to localhost:7233 and run the worker."""
    with (
        patch.object(worker.Client, "connect", new=AsyncMock()) as mock_connect,
        patch.object(worker, "Worker") as mock_worker_cls,
    ):
        mock_worker_cls.return_value.run = AsyncMock()

        await worker.main()

        mock_connect.assert_awaited_once_with("localhost:7233")
        mock_worker_cls.return_value.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_uses_temporal_address_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEMPORAL_ADDRESS overrides the default endpoint."""
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.example.com:7233")

    with (
        patch.object(worker.Client, "connect", new=AsyncMock()) as mock_connect,
        patch.object(worker, "Worker") as mock_worker_cls,
    ):
        mock_worker_cls.return_value.run = AsyncMock()

        await worker.main()

        mock_connect.assert_awaited_once_with("temporal.example.com:7233")


@pytest.mark.asyncio
async def test_main_registers_all_workflows_and_activities() -> None:
    """Worker is built on the network-changes queue with every workflow + activity."""
    with (
        patch.object(worker.Client, "connect", new=AsyncMock()),
        patch.object(worker, "Worker") as mock_worker_cls,
    ):
        mock_worker_cls.return_value.run = AsyncMock()

        await worker.main()

        _, kwargs = mock_worker_cls.call_args
        assert kwargs["task_queue"] == "network-changes"

        assert set(kwargs["workflows"]) == {
            NetworkChangeWorkflow,
            DriftRemediationWorkflow,
            EmergencyChangeWorkflow,
            OperationalOverrideWorkflow,
        }

        # All 17 activities registered (names are stable across the codebase).
        activity_names = {fn.__name__ for fn in kwargs["activities"]}
        assert activity_names == {
            "backup_running_config",
            "store_backup",
            "fetch_device_config",
            "fetch_running_config",
            "update_device_status",
            "deploy_config",
            "rollback_config",
            "validate_bgp",
            "validate_interfaces",
            "log_audit_event",
            "render_intended_config",
            "apply_override_config",
            "revert_override_config",
            "record_override_revert_failure",
            "check_reversion_safety",
            "update_override_status",
            "record_override_extension",
        }
