"""Unit tests for the OperationalOverrideWorkflow (Issues #48, #49).

Tests cover:
- Window expiry: apply, durable timer, safety check, revert to current SoT intent
- Early termination via the terminate_early signal (incident resolved)
- Window extension via the extend_window signal (incident ongoing)
- Apply failure aborts before the override is marked active
- Revert failure and unsafe reversion mark the override revert_failed
- Input validation (duration must be positive)
"""

from __future__ import annotations

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from synapse_workers.workflows.operational_override_workflow import (
    OperationalOverrideInput,
    OperationalOverrideWorkflow,
)
from tests.conftest import (
    _recorded_audit_events,
    _recorded_override_extensions,
    _recorded_override_revert_calls,
    _recorded_override_revert_failures,
    _recorded_override_status_updates,
    _recorded_store_backup_calls,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERRIDE_NAME = "leaf01-drain-2026-07-06"
DEVICE = "leaf01"
IP = "172.20.20.2"
OVERRIDE_CONFIG = '{"srl_nokia-interfaces:interface": [{"name": "ethernet-1/1", "admin-state": "disable"}]}'
ORIGINAL_CONFIG = '{"srl_nokia-interfaces:interface": [{"name": "ethernet-1/1", "admin-state": "enable"}]}'
INTENDED_CONFIG = '{"srl_nokia-interfaces:interface": [{"name": "ethernet-1/1", "admin-state": "enable", "mtu": 9214}]}'


# ---------------------------------------------------------------------------
# Mock activities
# ---------------------------------------------------------------------------


@activity.defn(name="fetch_running_config")
async def mock_fetch_running_config(
    device_hostname: str,
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
    port: int = 57400,
) -> str:
    return ORIGINAL_CONFIG


@activity.defn(name="store_backup")
async def mock_store_backup(device_hostname: str, config: str) -> None:
    _recorded_store_backup_calls.append((device_hostname, config))


@activity.defn(name="apply_override_config")
async def mock_apply(device_hostname: str, ip_address: str, override_config_json: str) -> bool:
    return True


@activity.defn(name="apply_override_config")
async def mock_apply_fail(device_hostname: str, ip_address: str, override_config_json: str) -> bool:
    raise ApplicationError("gNMI SET failed", non_retryable=True)


@activity.defn(name="update_override_status")
async def mock_update_override_status(override_name: str, status: str) -> None:
    _recorded_override_status_updates.append((override_name, status))


@activity.defn(name="check_reversion_safety")
async def mock_safety_ok(device_hostname: str, ip_address: str) -> bool:
    return True


@activity.defn(name="check_reversion_safety")
async def mock_safety_unsafe(device_hostname: str, ip_address: str) -> bool:
    return False


@activity.defn(name="fetch_device_config")
async def mock_fetch_device_config(device_hostname: str) -> dict:
    return {"hostname": device_hostname, "status": "active", "bgp": {}, "interfaces": {"interfaces": []}}


@activity.defn(name="render_intended_config")
async def mock_render_intended_config(interface_data: dict) -> str:
    return INTENDED_CONFIG


@activity.defn(name="revert_override_config")
async def mock_revert(device_hostname: str, ip_address: str, intended_config_json: str, active_seconds: float) -> bool:
    _recorded_override_revert_calls.append((device_hostname, intended_config_json, active_seconds))
    return True


@activity.defn(name="revert_override_config")
async def mock_revert_fail(
    device_hostname: str, ip_address: str, intended_config_json: str, active_seconds: float
) -> bool:
    raise ApplicationError("gNMI SET failed during revert", non_retryable=True)


@activity.defn(name="record_override_revert_failure")
async def mock_record_revert_failure(device_hostname: str, reason: str) -> None:
    _recorded_override_revert_failures.append((device_hostname, reason))


@activity.defn(name="record_override_extension")
async def mock_record_extension(override_name: str, additional_seconds: int) -> None:
    _recorded_override_extensions.append((override_name, additional_seconds))


@activity.defn(name="log_audit_event")
async def mock_log_audit(event_type: str, device_hostname: str, details: str) -> None:
    _recorded_audit_events.append((event_type, device_hostname, details))


def _activities(apply=mock_apply, safety=mock_safety_ok, revert=mock_revert) -> list:
    return [
        mock_fetch_running_config,
        mock_store_backup,
        apply,
        mock_update_override_status,
        safety,
        mock_fetch_device_config,
        mock_render_intended_config,
        revert,
        mock_record_revert_failure,
        mock_record_extension,
        mock_log_audit,
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(duration_seconds: int = 3600) -> OperationalOverrideInput:
    return OperationalOverrideInput(
        override_name=OVERRIDE_NAME,
        device_hostname=DEVICE,
        ip_address=IP,
        override_type="traffic_drain",
        override_config_json=OVERRIDE_CONFIG,
        reason="fibre outage INC-4242",
        operator="anton",
        duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_expires_and_reverts_to_current_intent() -> None:
    """Window expiry: apply, wait out the timer, revert to current SoT intent."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-override",
            workflows=[OperationalOverrideWorkflow],
            activities=_activities(),
        ),
    ):
        result = await env.client.execute_workflow(
            OperationalOverrideWorkflow.run,
            args=[_make_input(duration_seconds=3600)],
            id=f"override-test-expiry-{DEVICE}",
            task_queue="test-override",
        )
        assert result == "OVERRIDE_REVERTED"

    # Lifecycle in Infrahub: active while applied, reverted at the end.
    assert _recorded_override_status_updates == [(OVERRIDE_NAME, "active"), (OVERRIDE_NAME, "reverted")]
    # Original state was captured before the override was applied.
    assert (DEVICE, ORIGINAL_CONFIG) in _recorded_store_backup_calls
    # Auto-revert converges to the *current* SoT intent, not the snapshot (#161).
    assert len(_recorded_override_revert_calls) == 1
    device, config, active_seconds = _recorded_override_revert_calls[0]
    assert device == DEVICE
    assert config == INTENDED_CONFIG
    assert active_seconds >= 3600
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "OVERRIDE_INITIATED" in audit_types
    assert "OVERRIDE_APPLIED" in audit_types
    assert "OVERRIDE_REVERTED" in audit_types


@pytest.mark.asyncio
async def test_terminate_early_signal_cancels_override() -> None:
    """Early termination (incident resolved): revert immediately, mark cancelled."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-override",
            workflows=[OperationalOverrideWorkflow],
            activities=_activities(),
        ),
    ):
        handle = await env.client.start_workflow(
            OperationalOverrideWorkflow.run,
            args=[_make_input(duration_seconds=86400)],
            id=f"override-test-early-{DEVICE}",
            task_queue="test-override",
        )
        await handle.signal(OperationalOverrideWorkflow.terminate_early, "incident resolved")
        result = await handle.result()
        assert result == "OVERRIDE_CANCELLED"

    assert _recorded_override_status_updates == [(OVERRIDE_NAME, "active"), (OVERRIDE_NAME, "cancelled")]
    assert len(_recorded_override_revert_calls) == 1
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "OVERRIDE_TERMINATED_EARLY" in audit_types


@pytest.mark.asyncio
async def test_extend_window_signal_extends_and_counts() -> None:
    """Window extension (incident ongoing): revert only after the extended window."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-override",
            workflows=[OperationalOverrideWorkflow],
            activities=_activities(),
        ),
    ):
        handle = await env.client.start_workflow(
            OperationalOverrideWorkflow.run,
            args=[_make_input(duration_seconds=3600)],
            id=f"override-test-extend-{DEVICE}",
            task_queue="test-override",
        )
        await handle.signal(OperationalOverrideWorkflow.extend_window, args=[7200, "works overrunning"])
        result = await handle.result()
        assert result == "OVERRIDE_REVERTED"

    # Extension was tracked (metric activity) and audited.
    assert _recorded_override_extensions == [(OVERRIDE_NAME, 7200)]
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "OVERRIDE_EXTENDED" in audit_types
    # The override stayed active through the extended window before reverting.
    assert len(_recorded_override_revert_calls) == 1
    active_seconds = _recorded_override_revert_calls[0][2]
    assert active_seconds >= 3600 + 7200


@pytest.mark.asyncio
async def test_apply_failure_aborts_before_active() -> None:
    """If the override config cannot be applied, fail without marking it active."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-override",
            workflows=[OperationalOverrideWorkflow],
            activities=_activities(apply=mock_apply_fail),
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                OperationalOverrideWorkflow.run,
                args=[_make_input()],
                id=f"override-test-apply-fail-{DEVICE}",
                task_queue="test-override",
            )
        assert "apply failed" in str(exc_info.value.cause).lower()

    assert _recorded_override_status_updates == []
    assert _recorded_override_revert_calls == []
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "OVERRIDE_APPLY_FAILED" in audit_types


@pytest.mark.asyncio
async def test_revert_failure_marks_revert_failed() -> None:
    """If the revert deploy fails, record the failure and mark revert_failed."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-override",
            workflows=[OperationalOverrideWorkflow],
            activities=_activities(revert=mock_revert_fail),
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                OperationalOverrideWorkflow.run,
                args=[_make_input(duration_seconds=60)],
                id=f"override-test-revert-fail-{DEVICE}",
                task_queue="test-override",
            )
        assert "revert failed" in str(exc_info.value.cause).lower()

    assert _recorded_override_status_updates == [(OVERRIDE_NAME, "active"), (OVERRIDE_NAME, "revert_failed")]
    assert len(_recorded_override_revert_failures) == 1
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "OVERRIDE_REVERT_FAILED" in audit_types


@pytest.mark.asyncio
async def test_unsafe_reversion_marks_revert_failed_without_deploying() -> None:
    """If the safety check fails, do not touch the device; mark revert_failed."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-override",
            workflows=[OperationalOverrideWorkflow],
            activities=_activities(safety=mock_safety_unsafe),
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                OperationalOverrideWorkflow.run,
                args=[_make_input(duration_seconds=60)],
                id=f"override-test-unsafe-{DEVICE}",
                task_queue="test-override",
            )
        assert "safety" in str(exc_info.value.cause).lower()

    assert _recorded_override_status_updates == [(OVERRIDE_NAME, "active"), (OVERRIDE_NAME, "revert_failed")]
    assert _recorded_override_revert_calls == []
    assert len(_recorded_override_revert_failures) == 1
    audit_types = [event[0] for event in _recorded_audit_events]
    assert "OVERRIDE_REVERT_UNSAFE" in audit_types


@pytest.mark.asyncio
async def test_non_positive_duration_rejected() -> None:
    """Overrides are always time-bounded: duration_seconds must be > 0."""
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-override",
            workflows=[OperationalOverrideWorkflow],
            activities=_activities(),
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                OperationalOverrideWorkflow.run,
                args=[_make_input(duration_seconds=0)],
                id=f"override-test-zero-duration-{DEVICE}",
                task_queue="test-override",
            )
        assert "duration_seconds" in str(exc_info.value.cause)

    assert _recorded_override_status_updates == []
