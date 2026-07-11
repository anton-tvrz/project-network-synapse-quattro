"""Unit tests for the device-workflow trigger helper (Issue #165).

Temporal's workflow ID is the natural per-device mutex. Every mutating
workflow (change, drift, emergency, override) must start through
``start_device_workflow`` so that:

  - the workflow ID is derived from the device, not invented per caller;
  - all mutating workflow *types* share one device-scoped ID, so a drift
    remediation cannot fire mid-change on the same device;
  - a second start while one is running is REJECTED (explicit conflict
    policy), never raced;
  - sequential re-use after completion is allowed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from synapse_workers.triggers import TASK_QUEUE, device_workflow_id, start_device_workflow


@pytest.mark.unit
class TestDeviceWorkflowId:
    def test_id_when_built_is_device_scoped(self) -> None:
        assert device_workflow_id("leaf01") == "device-ops-leaf01"

    def test_id_when_same_device_is_identical_across_workflow_types(self) -> None:
        """One mutex per device: change/drift/override must collide, not race."""
        assert device_workflow_id("leaf01") == device_workflow_id("leaf01")

    def test_id_when_hostname_empty_fails_loud(self) -> None:
        with pytest.raises(ValueError, match="hostname"):
            device_workflow_id("")


@pytest.mark.unit
class TestStartDeviceWorkflow:
    def _client(self) -> AsyncMock:
        client = AsyncMock()
        client.start_workflow = AsyncMock(return_value="handle")
        return client

    def test_start_when_called_uses_device_scoped_id_and_explicit_policies(self) -> None:
        client = self._client()

        result = asyncio.run(
            start_device_workflow(
                client,
                "NetworkChangeWorkflow",
                device_hostname="leaf01",
                args=["leaf01", "172.20.20.11"],
            )
        )

        assert result == "handle"
        call = client.start_workflow.await_args
        assert call.args[0] == "NetworkChangeWorkflow"
        assert call.kwargs["id"] == "device-ops-leaf01"
        assert call.kwargs["task_queue"] == TASK_QUEUE
        assert call.kwargs["args"] == ["leaf01", "172.20.20.11"]
        # Explicit, not implicit: reject a concurrent start, allow sequential reuse.
        assert call.kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.FAIL
        assert call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE

    def test_start_when_memo_given_passes_it_through(self) -> None:
        client = self._client()

        asyncio.run(
            start_device_workflow(
                client,
                "OperationalOverrideWorkflow",
                device_hostname="leaf01",
                args=["input"],
                memo={"initiated_by": "alice"},
            )
        )

        assert client.start_workflow.await_args.kwargs["memo"] == {"initiated_by": "alice"}
