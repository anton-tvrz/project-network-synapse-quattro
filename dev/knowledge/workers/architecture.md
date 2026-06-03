# Temporal Workers Architecture

## Overview

The workers package (`synapse_workers`) provides durable, auditable workflow orchestration via Temporal. Workers execute long-running network automation tasks with built-in retry, timeout, and rollback capabilities.

## Components

### Worker Entry Point (`worker.py`)

Connects to the Temporal server and registers all workflows and activities on the `network-changes` task queue. Configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPORAL_ADDRESS` | `localhost:7233` | Temporal gRPC endpoint |

### Workflows (`workflows/`)

Workflows define the high-level orchestration logic. They are deterministic and call activities for side effects.

| Workflow | Purpose | Status |
|----------|---------|--------|
| `NetworkChangeWorkflow` | Standard network configuration change: fetch config, deploy, validate | Stub |
| `DriftRemediationWorkflow` | Detect and remediate configuration drift | Stub |
| `EmergencyChangeWorkflow` | Fast-track emergency changes with reduced validation | Stub |

### Activities (`activities/`)

Activities perform the actual work (API calls, device communication, etc.). They can be retried independently.

| Module | Activities | Status |
|--------|-----------|--------|
| `infrahub_activities.py` | `fetch_device_config`, `update_device_status` | Stub |
| `config_deployment_activities.py` | `deploy_config`, `rollback_config` | Stub |
| `device_backup_activities.py` | `backup_running_config`, `store_backup` | Stub |
| `validation_activities.py` | `validate_bgp`, `validate_interfaces` | Stub |

## Workflow Pattern

```
NetworkChangeWorkflow
  1. fetch_device_config()     # Query Infrahub for intended state
  2. backup_running_config()   # Backup current device state
  3. deploy_config()           # Push new config via gNMI
  4. validate_bgp()            # Verify BGP sessions established
  5. validate_interfaces()     # Verify interfaces operational
  6. update_device_status()    # Update Infrahub with deployment result
  (on failure) -> rollback_config()
```

## Testing Philosophy

This project follows strict TDD (see [ADR-0004](../../adr/0004-tdd-default-methodology.md)): a failing test defines the behaviour before any workflow or activity is written. Because workflows orchestrate irreversible device changes, the saga/rollback path is tested with the same rigour as the happy path.

| Component | Test type | What the tests prove |
|-----------|-----------|----------------------|
| Workflows (`workflows/`) | Unit (`temporalio.testing.WorkflowEnvironment`) | Activities execute in the correct order; on failure, the workflow triggers compensation (e.g. `rollback_config`); signals and timeouts are handled. Activities are mocked so the test is deterministic and fast. |
| Activities (`activities/`) | Unit (mocked dependencies) | Each activity honours its input/output contract; Infrahub/gNMI clients are mocked so no real device or API is touched. |
| Worker registration (`worker.py`) | Unit | All workflows and activities are registered on the `network-changes` task queue. |
| End-to-end orchestration | Integration | Workflow runs against a real Temporal test server and exercises the full deploy → validate → (rollback) path. |

The saga compensation test is mandatory for any workflow that mutates device state — a workflow is not "done" until its rollback path is proven under a failing activity. Unit tests live in `tests/unit/`, integration tests in `tests/integration/`. See [adding-workflows.md](../../guides/workers/adding-workflows.md) for the test-first workflow.

## Key Dependencies

| Package | Purpose |
|---------|---------|
| `temporalio` | Temporal SDK for Python (workflows, activities, worker) |
| `network-synapse` | Backend package (Infrahub client, config generation) |
| `pydantic` | Data validation for workflow inputs/outputs |
| `httpx` | HTTP client for Infrahub API calls in activities |

## Running the Worker

```bash
# Via invoke
uv run invoke workers.start

# Direct
TEMPORAL_ADDRESS=localhost:7233 uv run python -m synapse_workers.worker

# Via Docker
docker run -e TEMPORAL_ADDRESS=host.docker.internal:7233 synapse-worker
```
