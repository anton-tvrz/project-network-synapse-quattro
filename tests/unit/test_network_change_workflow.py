"""Unit tests for the NetworkChangeWorkflow.

Tests cover:
- Successful standard change (backup -> generate -> hygiene -> deploy -> validate)
- Hygiene failure aborts before any deploy (no rollback)
- Deploy failure triggers rollback
- Post-deploy validation failure triggers rollback

The workflow runs `generate_*_config` and `run_hygiene_checks` deterministically
inside the workflow sandbox, so the happy-path mock for `fetch_device_config`
returns realistic template vars built from the shared `spine01_device_config`
fixture — this renders valid SR Linux JSON that passes hygiene.
"""

from __future__ import annotations

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from synapse_workers.workflows.network_change_workflow import NetworkChangeWorkflow
from tests.conftest import _recorded_rollback_calls, _recorded_status_updates

DEVICE = "spine01"
IP = "172.20.20.3"
BACKUP_CONFIG = '{"interface": [{"name": "ethernet-1/1"}]}'
TASK_QUEUE = "test-network-change"

# Holds the device_data each test wants fetch_device_config to return.
_FETCH_RESULT: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Mock activities
# ---------------------------------------------------------------------------


@activity.defn(name="backup_running_config")
async def mock_backup(device_hostname: str, ip_address: str) -> str:
    return BACKUP_CONFIG


@activity.defn(name="store_backup")
async def mock_store_backup(device_hostname: str, config: str) -> None:
    return None


@activity.defn(name="fetch_device_config")
async def mock_fetch_device_config(device_hostname: str) -> dict:
    return _FETCH_RESULT["data"]


@activity.defn(name="deploy_config")
async def mock_deploy(device_hostname: str, ip_address: str, config_json: str) -> bool:
    return True


@activity.defn(name="deploy_config")
async def mock_deploy_fail(device_hostname: str, ip_address: str, config_json: str) -> bool:
    raise ApplicationError("gNMI deploy failed", non_retryable=True)


@activity.defn(name="rollback_config")
async def mock_rollback(device_hostname: str, ip_address: str, backup_config_json: str) -> bool:
    _recorded_rollback_calls.append((device_hostname, ip_address, backup_config_json))
    return True


@activity.defn(name="validate_bgp")
async def mock_validate_bgp(device_hostname: str, ip_address: str) -> bool:
    return True


@activity.defn(name="validate_bgp")
async def mock_validate_bgp_fail(device_hostname: str, ip_address: str) -> bool:
    raise ApplicationError("BGP not established", non_retryable=True)


@activity.defn(name="validate_interfaces")
async def mock_validate_interfaces(device_hostname: str, ip_address: str, intended_interfaces: list) -> dict:
    return {"passed": True, "device": device_hostname}


@activity.defn(name="update_device_status")
async def mock_update_status(device_hostname: str, status: str) -> None:
    _recorded_status_updates.append((device_hostname, status))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_device_data(spine01_device_config) -> dict:
    """Realistic template vars that render valid, hygiene-passing configs."""
    iface_vars = spine01_device_config.to_interface_template_vars().model_dump()
    # The hygiene checker only accepts ethernet-*/system* names, so use the
    # SR Linux system loopback name instead of the fixture's "loopback0".
    for iface in iface_vars["interfaces"]:
        if iface["name"] == "loopback0":
            iface["name"] = "system0"
    return {
        "bgp": spine01_device_config.to_bgp_template_vars().model_dump(),
        "interfaces": iface_vars,
    }


def _activities(deploy=mock_deploy, validate_bgp=mock_validate_bgp):
    return [
        mock_backup,
        mock_store_backup,
        mock_fetch_device_config,
        deploy,
        mock_rollback,
        validate_bgp,
        mock_validate_interfaces,
        mock_update_status,
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_change_success(spine01_device_config) -> None:
    """Happy path: backup -> generate -> hygiene -> deploy -> validate -> active."""
    _FETCH_RESULT["data"] = _valid_device_data(spine01_device_config)

    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[NetworkChangeWorkflow],
            activities=_activities(),
            workflow_runner=UnsandboxedWorkflowRunner(),
            # The workflow signals failure with plain RuntimeError; without this
            # Temporal treats it as a workflow-task bug and retries forever.
            workflow_failure_exception_types=[RuntimeError],
        ),
    ):
        result = await env.client.execute_workflow(
            NetworkChangeWorkflow.run,
            args=[DEVICE, IP],
            id=f"netchange-success-{DEVICE}",
            task_queue=TASK_QUEUE,
        )

    assert result == "SUCCESS"
    assert (DEVICE, "active") in _recorded_status_updates
    assert _recorded_rollback_calls == []


@pytest.mark.asyncio
async def test_network_change_hygiene_failure_aborts_without_rollback(spine01_device_config) -> None:
    """Invalid BGP ASN fails hygiene before deploy — abort, mark maintenance, no rollback."""
    bad = _valid_device_data(spine01_device_config)
    bad["bgp"]["local_asn"] = 0  # renders autonomous-system 0 -> hygiene fails

    _FETCH_RESULT["data"] = bad

    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[NetworkChangeWorkflow],
            activities=_activities(),
            workflow_runner=UnsandboxedWorkflowRunner(),
            # The workflow signals failure with plain RuntimeError; without this
            # Temporal treats it as a workflow-task bug and retries forever.
            workflow_failure_exception_types=[RuntimeError],
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                NetworkChangeWorkflow.run,
                args=[DEVICE, IP],
                id=f"netchange-hygiene-fail-{DEVICE}",
                task_queue=TASK_QUEUE,
            )

    assert "Hygiene" in str(exc_info.value.cause)
    assert (DEVICE, "maintenance") in _recorded_status_updates
    assert _recorded_rollback_calls == []


@pytest.mark.asyncio
async def test_network_change_deploy_failure_rolls_back(spine01_device_config) -> None:
    """Deploy failure triggers rollback and marks maintenance."""
    _FETCH_RESULT["data"] = _valid_device_data(spine01_device_config)

    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[NetworkChangeWorkflow],
            activities=_activities(deploy=mock_deploy_fail),
            workflow_runner=UnsandboxedWorkflowRunner(),
            workflow_failure_exception_types=[RuntimeError],
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                NetworkChangeWorkflow.run,
                args=[DEVICE, IP],
                id=f"netchange-deploy-fail-{DEVICE}",
                task_queue=TASK_QUEUE,
            )

    assert "rolled back" in str(exc_info.value.cause)
    assert any(call[0] == DEVICE and call[2] == BACKUP_CONFIG for call in _recorded_rollback_calls)
    assert (DEVICE, "maintenance") in _recorded_status_updates


@pytest.mark.asyncio
async def test_network_change_validation_failure_rolls_back(spine01_device_config) -> None:
    """Post-deploy validation failure triggers rollback and marks maintenance."""
    _FETCH_RESULT["data"] = _valid_device_data(spine01_device_config)

    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[NetworkChangeWorkflow],
            activities=_activities(validate_bgp=mock_validate_bgp_fail),
            workflow_runner=UnsandboxedWorkflowRunner(),
            workflow_failure_exception_types=[RuntimeError],
        ),
    ):
        with pytest.raises(WorkflowFailureError) as exc_info:
            await env.client.execute_workflow(
                NetworkChangeWorkflow.run,
                args=[DEVICE, IP],
                id=f"netchange-validate-fail-{DEVICE}",
                task_queue=TASK_QUEUE,
            )

    assert "Validation failed" in str(exc_info.value.cause)
    assert any(call[0] == DEVICE and call[2] == BACKUP_CONFIG for call in _recorded_rollback_calls)
    assert (DEVICE, "maintenance") in _recorded_status_updates
