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
    DriftAction,
    DriftRemediationWorkflow,
    DriftSeverity,
    classify_drift,
    decide_drift_action,
)
from tests.conftest import (
    _recorded_audit_events,
    _recorded_status_updates,
    _recorded_store_backup_calls,
)

# ---------------------------------------------------------------------------
# Helpers — mock activities
# ---------------------------------------------------------------------------

DEVICE = "spine01"
IP = "172.20.20.3"

INTENDED_CONFIG = '{"interface": [{"name": "ethernet-1/1"}]}'
RUNNING_CONFIG_CLEAN = '{"interface": [{"name": "ethernet-1/1"}]}'
RUNNING_CONFIG_DRIFTED = '{"interface": [{"name": "ethernet-1/1", "admin-state": "disable"}]}'
RUNNING_CONFIG_COSMETIC = '{"interface": [{"name": "ethernet-1/1", "description": "temp note"}]}'


@activity.defn(name="fetch_device_config")
async def mock_fetch_device_config(device_hostname: str) -> dict:
    return {
        "hostname": device_hostname,
        "ip_address": IP,
        "status": "active",
        "bgp": {"router_id": "10.1.0.1", "local_asn": 65000, "sessions": []},
        "interfaces": {"hostname": device_hostname, "interfaces": [{"name": "ethernet-1/1"}]},
    }


@activity.defn(name="fetch_device_config")
async def mock_fetch_device_config_maintenance(device_hostname: str) -> dict:
    return {
        "hostname": device_hostname,
        "ip_address": IP,
        "status": "maintenance",
        "bgp": {"router_id": "10.1.0.1", "local_asn": 65000, "sessions": []},
        "interfaces": {"hostname": device_hostname, "interfaces": [{"name": "ethernet-1/1"}]},
    }


@activity.defn(name="fetch_running_config")
async def mock_fetch_running_config_cosmetic(device_hostname: str, ip_address: str) -> str:
    return RUNNING_CONFIG_COSMETIC


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
    _recorded_status_updates.append((device_hostname, status))


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
    _recorded_store_backup_calls.append((device_hostname, config))


@activity.defn(name="log_audit_event")
async def mock_log_audit_event(event_type: str, device_hostname: str, details: str) -> None:
    _recorded_audit_events.append((event_type, device_hostname, details))


# ---------------------------------------------------------------------------
# classify_drift unit tests (pure function, no Temporal needed)
# ---------------------------------------------------------------------------


class TestClassifyDrift:
    """Test drift classification logic."""

    def test_no_drift_when_configs_match(self) -> None:
        result = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_CLEAN)
        assert result.has_drift is False
        assert result.severity == DriftSeverity.NONE

    def test_drift_severity_when_only_description_changed_returns_cosmetic(self) -> None:
        result = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_COSMETIC)
        assert result.has_drift is True
        assert result.severity == DriftSeverity.COSMETIC

    def test_drift_severity_when_admin_state_changed_returns_critical(self) -> None:
        result = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_DRIFTED)
        assert result.has_drift is True
        assert result.severity == DriftSeverity.CRITICAL  # admin-state change is critical

    def test_drift_diff_when_configs_differ_includes_details(self) -> None:
        result = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_DRIFTED)
        assert result.has_drift is True
        assert result.diff != ""


class TestDecideDriftAction:
    """Drift response policy (Issue #154): severity + device status -> action."""

    def test_no_drift_takes_no_action(self) -> None:
        drift = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_CLEAN)
        assert decide_drift_action(drift, "active") == DriftAction.NONE

    def test_critical_drift_on_active_device_remediates(self) -> None:
        drift = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_DRIFTED)
        assert decide_drift_action(drift, "active") == DriftAction.REMEDIATE

    def test_cosmetic_drift_is_logged_not_remediated(self) -> None:
        drift = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_COSMETIC)
        assert decide_drift_action(drift, "active") == DriftAction.LOG_ONLY

    def test_maintenance_suppresses_remediation_even_for_critical_drift(self) -> None:
        """An out-of-band fix during maintenance must not be silently reverted."""
        drift = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_DRIFTED)
        assert decide_drift_action(drift, "maintenance") == DriftAction.SUPPRESS_MAINTENANCE

    def test_maintenance_suppresses_cosmetic_drift_too(self) -> None:
        drift = classify_drift(INTENDED_CONFIG, RUNNING_CONFIG_COSMETIC)
        assert decide_drift_action(drift, "maintenance") == DriftAction.SUPPRESS_MAINTENANCE


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

DRIFT_ACTIVITIES_COSMETIC = [
    mock_fetch_device_config,
    mock_render_intended_config,
    mock_fetch_running_config_cosmetic,
    mock_deploy_config,
    mock_validate_bgp,
    mock_validate_interfaces,
    mock_update_device_status,
    mock_backup_running_config,
    mock_store_backup,
    mock_log_audit_event,
]

DRIFT_ACTIVITIES_MAINTENANCE = [
    mock_fetch_device_config_maintenance,
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
async def test_run_when_cosmetic_drift_logs_without_remediating() -> None:
    """Cosmetic drift is audited but never redeployed (Issue #154)."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-drift",
            workflows=[DriftRemediationWorkflow],
            activities=DRIFT_ACTIVITIES_COSMETIC,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        result = await env.client.execute_workflow(
            DriftRemediationWorkflow.run,
            args=[DEVICE, IP],
            id=f"drift-test-cosmetic-{DEVICE}",
            task_queue="test-drift",
        )
        assert result == "DRIFT_LOGGED"
        assert _recorded_store_backup_calls == []
        event_types = [e[0] for e in _recorded_audit_events]
        assert "DRIFT_DETECTED" in event_types
        assert "DRIFT_LOGGED" in event_types


@pytest.mark.asyncio
async def test_run_when_device_in_maintenance_suppresses_remediation() -> None:
    """Critical drift on a device in maintenance is suppressed, not reverted (Issue #154)."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-drift",
            workflows=[DriftRemediationWorkflow],
            activities=DRIFT_ACTIVITIES_MAINTENANCE,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        result = await env.client.execute_workflow(
            DriftRemediationWorkflow.run,
            args=[DEVICE, IP],
            id=f"drift-test-maintenance-{DEVICE}",
            task_queue="test-drift",
        )
        assert result == "DRIFT_SUPPRESSED_MAINTENANCE"
        assert _recorded_store_backup_calls == []
        event_types = [e[0] for e in _recorded_audit_events]
        assert "DRIFT_SUPPRESSED_MAINTENANCE" in event_types


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

    # Failure-path observability: device should be quarantined and the failure audited.
    assert (DEVICE, "maintenance") in _recorded_status_updates
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "DRIFT_REMEDIATION_FAILED" in audit_types


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

    # Failure-path observability: device quarantined and validation failure audited.
    assert (DEVICE, "maintenance") in _recorded_status_updates
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "DRIFT_VALIDATION_FAILED" in audit_types


# ---------------------------------------------------------------------------
# Retry policy on store_backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_backup_retries_on_transient_failure() -> None:
    """store_backup should be retried on transient failure (proves a retry policy is wired)."""
    call_count = 0

    @activity.defn(name="store_backup")
    async def flaky_store_backup(device_hostname: str, config: str) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient storage failure")

    activities = [
        mock_fetch_device_config,
        mock_render_intended_config,
        mock_fetch_running_config_drifted,
        mock_deploy_config,
        mock_validate_bgp,
        mock_validate_interfaces,
        mock_update_device_status,
        mock_backup_running_config,
        flaky_store_backup,
        mock_log_audit_event,
    ]

    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-drift",
            workflows=[DriftRemediationWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        result = await env.client.execute_workflow(
            DriftRemediationWorkflow.run,
            args=[DEVICE, IP],
            id=f"drift-test-store-retry-{DEVICE}",
            task_queue="test-drift",
        )
        assert result == "REMEDIATED"
        assert call_count >= 2, "store_backup should have been retried after transient failure"
