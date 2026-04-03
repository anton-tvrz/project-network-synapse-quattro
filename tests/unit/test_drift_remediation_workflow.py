"""Unit tests for the DriftRemediationWorkflow.

Tests cover:
- No-drift scenario (intended == actual) — no remediation
- Drift detected — triggers backup, re-deploy, validate cycle
- Drift detected but deploy fails — raises, marks device maintenance
- Drift detected but validation fails — raises, marks device maintenance
- Severity classification: critical vs cosmetic drift
"""

from __future__ import annotations

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from synapse_workers.workflows.drift_remediation_workflow import (
    DriftRemediationWorkflow,
    DriftSeverity,
    classify_drift,
)

# ---------------------------------------------------------------------------
# Helpers — mock activities
# ---------------------------------------------------------------------------

DEVICE = "spine01"
IP = "172.20.20.3"

INTENDED_CONFIG = '{"interface": [{"name": "ethernet-1/1"}]}'
RUNNING_CONFIG_CLEAN = '{"interface": [{"name": "ethernet-1/1"}]}'
RUNNING_CONFIG_DRIFTED = '{"interface": [{"name": "ethernet-1/1", "admin-state": "disable"}]}'


@activity.defn(name="fetch_device_config")
async def mock_fetch_device_config(device_hostname: str) -> dict:
    return {
        "hostname": device_hostname,
        "ip_address": IP,
        "bgp": {"router_id": "10.1.0.1", "local_asn": 65000, "sessions": []},
        "interfaces": {"hostname": device_hostname, "interfaces": [{"name": "ethernet-1/1"}]},
    }


@activity.defn(name="render_intended_config")
async def mock_render_intended_config(interface_data: dict) -> str:
    return INTENDED_CONFIG


@activity.defn(name="fetch_running_config")
async def mock_fetch_running_config_clean(device_hostname: str, ip_address: str) -> str:
    return RUNNING_CONFIG_CLEAN


@activity.defn(name="fetch_running_config")
async def mock_fetch_running_config_drifted(device_hostname: str, ip_address: str) -> str:
    return RUNNING_CONFIG_DRIFTED


@activity.defn(name="deploy_config")
async def mock_deploy_config(device_hostname: str, ip_address: str, config_json: str) -> bool:
    return True


@activity.defn(name="deploy_config")
async def mock_deploy_config_fail(device_hostname: str, ip_address: str, config_json: str) -> bool:
    raise ApplicationError("Deploy failed", non_retryable=True)


@activity.defn(name="validate_bgp")
async def mock_validate_bgp(device_hostname: str, ip_address: str) -> bool:
    return True


@activity.defn(name="validate_bgp")
async def mock_validate_bgp_fail(device_hostname: str, ip_address: str) -> bool:
    raise ApplicationError("BGP validation failed", non_retryable=True)


@activity.defn(name="validate_interfaces")
async def mock_validate_interfaces(device_hostname: str, ip_address: str, intended_interfaces: list[dict]) -> dict:
    return {"passed": True, "device": device_hostname, "details": []}


@activity.defn(name="update_device_status")
async def mock_update_device_status(device_hostname: str, status: str) -> None:
    pass


@activity.defn(name="backup_running_config")
async def mock_backup_running_config(
    device_hostname: str,
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
) -> str:
    return RUNNING_CONFIG_CLEAN


@activity.defn(name="store_backup")
async def mock_store_backup(device_hostname: str, config: str) -> None:
    pass


@activity.defn(name="log_audit_event")
async def mock_log_audit_event(event_type: str, device_hostname: str, details: str) -> None:
    pass


# ---------------------------------------------------------------------------
# classify_drift unit tests (pure function, no Temporal needed)
# ---------------------------------------------------------------------------


class TestClassifyDrift:
    """Test drift classification logic."""

    def test_no_drift_when_configs_match(self) -> None:
        result = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_CLEAN)
        assert result.has_drift is False
        assert result.severity == DriftSeverity.NONE

    def test_drift_severity_when_admin_state_changed_returns_critical(self) -> None:
        result = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_DRIFTED)
        assert result.has_drift is True
        assert result.severity == DriftSeverity.CRITICAL  # admin-state change is critical

    def test_drift_diff_when_configs_differ_includes_details(self) -> None:
        result = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_DRIFTED)
        assert result.has_drift is True
        assert result.diff != ""


# ---------------------------------------------------------------------------
# Workflow tests (Temporal local test environment)
# ---------------------------------------------------------------------------

DRIFT_ACTIVITIES_HAPPY = [
    mock_fetch_device_config,
    mock_render_intended_config,
    mock_fetch_running_config_clean,
    mock_deploy_config,
    mock_validate_bgp,
    mock_validate_interfaces,
    mock_update_device_status,
    mock_backup_running_config,
    mock_store_backup,
    mock_log_audit_event,
]

DRIFT_ACTIVITIES_DRIFTED = [
    mock_fetch_device_config,
    mock_render_intended_config,
    mock_fetch_running_config_drifted,
    mock_deploy_config,
    mock_validate_bgp,
    mock_validate_interfaces,
    mock_update_device_status,
    mock_backup_running_config,
    mock_store_backup,
    mock_log_audit_event,
]

DRIFT_ACTIVITIES_DEPLOY_FAIL = [
    mock_fetch_device_config,
    mock_render_intended_config,
    mock_fetch_running_config_drifted,
    mock_deploy_config_fail,
    mock_validate_bgp,
    mock_validate_interfaces,
    mock_update_device_status,
    mock_backup_running_config,
    mock_store_backup,
    mock_log_audit_event,
]

DRIFT_ACTIVITIES_VALIDATION_FAIL = [
    mock_fetch_device_config,
    mock_render_intended_config,
    mock_fetch_running_config_drifted,
    mock_deploy_config,
    mock_validate_bgp_fail,
    mock_validate_interfaces,
    mock_update_device_status,
    mock_backup_running_config,
    mock_store_backup,
    mock_log_audit_event,
]


@pytest.mark.asyncio
async def test_run_when_configs_match_returns_no_drift() -> None:
    """When intended == running, workflow reports no drift and takes no action."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-drift",
            workflows=[DriftRemediationWorkflow],
            activities=DRIFT_ACTIVITIES_HAPPY,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        result = await env.client.execute_workflow(
            DriftRemediationWorkflow.run,
            args=[DEVICE, IP],
            id=f"drift-test-clean-{DEVICE}",
            task_queue="test-drift",
        )
        assert result == "NO_DRIFT"


@pytest.mark.asyncio
async def test_run_when_drift_detected_returns_remediated() -> None:
    """When drift is detected, workflow remediates and returns REMEDIATED."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-drift",
            workflows=[DriftRemediationWorkflow],
            activities=DRIFT_ACTIVITIES_DRIFTED,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        result = await env.client.execute_workflow(
            DriftRemediationWorkflow.run,
            args=[DEVICE, IP],
            id=f"drift-test-remediated-{DEVICE}",
            task_queue="test-drift",
        )
        assert result == "REMEDIATED"


@pytest.mark.asyncio
async def test_run_when_deploy_fails_raises_application_error() -> None:
    """When drift is detected but deploy fails, workflow raises ApplicationError."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-drift",
            workflows=[DriftRemediationWorkflow],
            activities=DRIFT_ACTIVITIES_DEPLOY_FAIL,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                DriftRemediationWorkflow.run,
                args=[DEVICE, IP],
                id=f"drift-test-deploy-fail-{DEVICE}",
                task_queue="test-drift",
            )
        assert "Drift remediation failed" in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_run_when_validation_fails_raises_application_error() -> None:
    """When drift is detected and deployed but validation fails, workflow raises."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-drift",
            workflows=[DriftRemediationWorkflow],
            activities=DRIFT_ACTIVITIES_VALIDATION_FAIL,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                DriftRemediationWorkflow.run,
                args=[DEVICE, IP],
                id=f"drift-test-validate-fail-{DEVICE}",
                task_queue="test-drift",
            )
        assert "validation error" in str(exc_info.value.cause)
