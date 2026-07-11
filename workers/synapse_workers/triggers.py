"""Start device-mutating workflows with per-device mutual exclusion (Issue #165).

Temporal's workflow ID is the natural mutex. Every workflow that mutates a
device (change, drift remediation, emergency change, operational override)
must be started through :func:`start_device_workflow`, which derives the
workflow ID from the device — one shared ID across all mutating workflow
*types*, because the dangerous race is cross-type: a drift remediation firing
mid-change would back up a half-applied config and roll back to the wrong
baseline (compounding #164).

Policies are explicit, not implicit defaults:

  - ``id_conflict_policy=FAIL``: a second start while one is running is
    rejected with ``WorkflowAlreadyStartedError`` — callers surface it as
    "device busy" (the portal returns HTTP 409), never race.
  - ``id_reuse_policy=ALLOW_DUPLICATE``: sequential operations on a device
    re-use the ID after the previous workflow closes, regardless of outcome.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

if TYPE_CHECKING:
    from temporalio.client import Client, WorkflowHandle

TASK_QUEUE = "network-changes"


def device_workflow_id(device_hostname: str) -> str:
    """The device-scoped Temporal workflow ID shared by all mutating workflows."""
    if not device_hostname:
        raise ValueError("device hostname must be non-empty to build a workflow ID")
    return f"device-ops-{device_hostname}"


async def start_device_workflow(
    client: Client,
    workflow: str,
    *,
    device_hostname: str,
    args: list[Any],
    memo: dict[str, Any] | None = None,
    task_queue: str = TASK_QUEUE,
) -> WorkflowHandle:
    """Start a device-mutating workflow under the device mutex.

    Raises ``temporalio.exceptions.WorkflowAlreadyStartedError`` when another
    mutating workflow is already running for the device.
    """
    return await client.start_workflow(
        workflow,
        args=args,
        id=device_workflow_id(device_hostname),
        task_queue=task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        memo=memo,
    )
