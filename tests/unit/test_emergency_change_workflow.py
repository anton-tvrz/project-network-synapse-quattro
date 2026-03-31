"""Unit tests for the EmergencyChangeWorkflow.

Tests cover:
- Successful emergency change with audit trail
- Emergency change with auto-reversion timer
- Emergency deploy failure triggers rollback
- Post-deploy validation failure triggers rollback
"""

from __future__ import annotations

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from synapse_workers.workflows.emergency_change_workflow import (
    EmergencyChangeInput,
    EmergencyChangeWorkflow,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEVICE = "leaf01"
IP = "172.20.20.2"
EMERGENCY_CONFIG = '{"srl_nokia-interfaces:interface": [{"name": "ethernet-1/1", "admin-state": "disable"}]}'
BACKUP_CONFIG = '{"srl_nokia-interfaces:interface": [{"name": "ethernet-1/1"}]}'


# ---------------------------------------------------------------------------
# Mock activities
# ---------------------------------------------------------------------------


@activity.defn(name="backup_running_config")
async def mock_backup(
    device_hostname: str,
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
) -> str:
    return BACKUP_CONFIG


@activity.defn(name="store_backup")
async def mock_store_backup(device_hostname: str, config: str) -> None:
    pass


@activity.defn(name="deploy_config")
async def mock_deploy(device_hostname: str, ip_address: str, config_json: str) -> bool:
    return True


@activity.defn(name="deploy_config")
async def mock_deploy_fail(device_hostname: str, ip_address: str, config_json: str) -> bool:
    raise ApplicationError("Emergency deploy failed", non_retryable=True)


@activity.defn(name="rollback_config")
async def mock_rollback(device_hostname: str, ip_address: str, backup_config_json: str) -> bool:
    return True


@activity.defn(name="validate_bgp")
async def mock_validate_bgp(device_hostname: str, ip_address: str) -> bool:
    return True


@activity.defn(name="validate_interfaces")
async def mock_validate_interfaces(device_hostname: str, ip_address: str, intended_interfaces: list[dict]) -> dict:
    return {"passed": True, "device": device_hostname, "details": []}


@activity.defn(name="validate_bgp")
async def mock_validate_bgp_fail(device_hostname: str, ip_address: str) -> bool:
    raise ApplicationError("BGP validation failed", non_retryable=True)


@activity.defn(name="update_device_status")
async def mock_update_status(device_hostname: str, status: str) -> None:
    pass


@activity.defn(name="log_audit_event")
async def mock_log_audit(event_type: str, device_hostname: str, details: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Shared activity lists
# ---------------------------------------------------------------------------

ACTIVITIES_HAPPY = [
    mock_backup,
    mock_store_backup,
    mock_deploy,
    mock_validate_bgp,
    mock_validate_interfaces,
    mock_update_status,
    mock_log_audit,
    mock_rollback,
]

ACTIVITIES_DEPLOY_FAIL = [
    mock_backup,
    mock_store_backup,
    mock_deploy_fail,
    mock_validate_bgp,
    mock_validate_interfaces,
    mock_update_status,
    mock_log_audit,
    mock_rollback,
]

ACTIVITIES_VALIDATE_FAIL = [
    mock_backup,
    mock_store_backup,
    mock_deploy,
    mock_validate_bgp_fail,
    mock_validate_interfaces,
    mock_update_status,
    mock_log_audit,
    mock_rollback,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(
    ttl_seconds: int = 0,
    reason: str = "BGP flap on leaf01 causing packet loss",
    operator: str = "anton",
) -> EmergencyChangeInput:
    return EmergencyChangeInput(
        device_hostname=DEVICE,
        ip_address=IP,
        config_json=EMERGENCY_CONFIG,
        reason=reason,
        operator=operator,
        ttl_seconds=ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_change_success() -> None:
    """Successful emergency change: backup, deploy, validate, audit."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-emergency",
            workflows=[EmergencyChangeWorkflow],
            activities=ACTIVITIES_HAPPY,
        ),
    ):
        result = await env.client.execute_workflow(
            EmergencyChangeWorkflow.run,
            args=[_make_input()],
            id=f"emergency-test-success-{DEVICE}",
            task_queue="test-emergency",
        )
        assert result == "EMERGENCY_APPLIED"


@pytest.mark.asyncio
async def test_emergency_change_deploy_failure_rolls_back() -> None:
    """If emergency deploy fails, rollback to backup and raise."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-emergency",
            workflows=[EmergencyChangeWorkflow],
            activities=ACTIVITIES_DEPLOY_FAIL,
        ),
    ):
        from temporalio.client import WorkflowFailureError

        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                EmergencyChangeWorkflow.run,
                args=[_make_input()],
                id=f"emergency-test-deploy-fail-{DEVICE}",
                task_queue="test-emergency",
            )
        assert "Emergency deploy failed" in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_emergency_change_validation_failure_rolls_back() -> None:
    """If post-deploy validation fails, rollback to backup and raise."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-emergency",
            workflows=[EmergencyChangeWorkflow],
            activities=ACTIVITIES_VALIDATE_FAIL,
        ),
    ):
        from temporalio.client import WorkflowFailureError

        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                EmergencyChangeWorkflow.run,
                args=[_make_input()],
                id=f"emergency-test-validate-fail-{DEVICE}",
                task_queue="test-emergency",
            )
        assert "Emergency validation failed" in str(exc_info.value.cause)


@pytest.mark.asyncio
async def test_emergency_change_with_ttl_schedules_reversion() -> None:
    """When ttl_seconds > 0, workflow should schedule auto-reversion after TTL expires."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-emergency",
            workflows=[EmergencyChangeWorkflow],
            activities=ACTIVITIES_HAPPY,
        ),
    ):
        # TTL of 60 seconds — workflow applies change, then waits and reverts
        result = await env.client.execute_workflow(
            EmergencyChangeWorkflow.run,
            args=[_make_input(ttl_seconds=60)],
            id=f"emergency-test-ttl-{DEVICE}",
            task_queue="test-emergency",
        )
        assert result == "EMERGENCY_REVERTED"
