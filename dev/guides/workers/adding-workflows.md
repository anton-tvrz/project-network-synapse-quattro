# Adding Temporal Workflows

## Overview

Temporal workflows orchestrate multi-step network automation tasks. Each workflow calls activities for side effects (API calls, device communication).

## Steps

### 1. Write the Test File

Create `tests/unit/test_<workflow>_workflow.py` with expected activity sequence and saga compensation:

```python
# tests/unit/test_my_workflow_workflow.py
import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

@pytest.mark.unit
async def test_my_workflow_happy_path(workflow_env: WorkflowEnvironment):
    """Workflow executes all activities in order on success."""
    # Define mock activities
    # Start workflow
    # Assert result and activity call order

@pytest.mark.unit
async def test_my_workflow_saga_compensation(workflow_env: WorkflowEnvironment):
    """Workflow triggers rollback when an activity fails."""
    # Define mock activity that raises
    # Start workflow
    # Assert rollback activity was called
```

Run the test — it should **fail** (RED) because the workflow doesn't exist yet.

### 2. Define the Workflow

Create workflow class in `workers/synapse_workers/workflows/`:

```python
# workers/synapse_workers/workflows/my_workflow.py
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from synapse_workers.activities.my_activities import my_activity

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self, device_name: str) -> str:
        result = await workflow.execute_activity(
            my_activity,
            device_name,
            start_to_close_timeout=timedelta(seconds=60),
        )
        return result["status"]
```

### 3. Define Activities

Create activity functions in `workers/synapse_workers/activities/`:

```python
# workers/synapse_workers/activities/my_activities.py
from temporalio import activity

@activity.defn
async def my_activity(device_name: str) -> dict:
    """Perform some network operation."""
    # Call Infrahub API, gNMI, etc.
    return {"status": "success", "device": device_name}
```

### 4. Run Tests (GREEN)

```bash
# Run unit tests — should now pass
uv run pytest tests/unit/test_my_workflow_workflow.py -v

# Run all unit tests to check for regressions
uv run invoke backend.test-unit
```

### 5. Integration Test with Temporal Test Server

Register in worker and run integration tests:

Add workflow and activities to `workers/synapse_workers/worker.py`:

```python
from synapse_workers.workflows.my_workflow import MyWorkflow
from synapse_workers.activities.my_activities import my_activity

worker = Worker(
    client,
    task_queue="network-changes",
    workflows=[MyWorkflow],
    activities=[my_activity],
)
```

```bash
# Integration test (requires running Temporal server)
uv run pytest tests/integration/ -k "my_workflow" -v

# Start the worker
uv run invoke workers.start
```
