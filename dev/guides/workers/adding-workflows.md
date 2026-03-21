# Adding Temporal Workflows

## Overview

Temporal workflows orchestrate multi-step network automation tasks. Each workflow calls activities for side effects (API calls, device communication).

## Steps

### 1. Define Activities

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

### 2. Create the Workflow

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

### 3. Register in Worker

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

### 4. Test

```bash
# Unit test the workflow logic
uv run pytest tests/unit/ -k "my_workflow" -v

# Integration test (requires running Temporal server)
uv run pytest tests/integration/ -k "my_workflow" -v
```

### 5. Run

```bash
# Start the worker
uv run invoke workers.start

# Trigger the workflow (via Temporal UI or SDK)
```
