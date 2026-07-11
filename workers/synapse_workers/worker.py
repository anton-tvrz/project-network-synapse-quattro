"""Temporal worker entry point."""

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from synapse_workers.activities.config_deployment_activities import deploy_config, rollback_config
from synapse_workers.activities.device_backup_activities import backup_running_config, store_backup
from synapse_workers.activities.drift_activities import fetch_running_config, log_audit_event, render_intended_config
from synapse_workers.activities.infrahub_activities import fetch_device_config, update_device_status
from synapse_workers.activities.override_activities import (
    apply_override_config,
    check_reversion_safety,
    record_override_extension,
    record_override_revert_failure,
    revert_override_config,
    update_override_status,
)
from synapse_workers.activities.validation_activities import validate_bgp, validate_interfaces
from synapse_workers.metrics import start_metrics_server
from synapse_workers.triggers import TASK_QUEUE
from synapse_workers.workflows.drift_remediation_workflow import DriftRemediationWorkflow
from synapse_workers.workflows.emergency_change_workflow import EmergencyChangeWorkflow
from synapse_workers.workflows.network_change_workflow import NetworkChangeWorkflow
from synapse_workers.workflows.operational_override_workflow import OperationalOverrideWorkflow


async def main() -> None:
    metrics_port = int(os.getenv("WORKER_METRICS_PORT", "9464"))
    if metrics_port:
        start_metrics_server(metrics_port)
        print(f"Metrics exposed on :{metrics_port}/metrics")

    temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(temporal_address)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            NetworkChangeWorkflow,
            DriftRemediationWorkflow,
            EmergencyChangeWorkflow,
            OperationalOverrideWorkflow,
        ],
        activities=[
            backup_running_config,
            store_backup,
            fetch_device_config,
            fetch_running_config,
            update_device_status,
            deploy_config,
            rollback_config,
            validate_bgp,
            validate_interfaces,
            log_audit_event,
            render_intended_config,
            apply_override_config,
            revert_override_config,
            record_override_revert_failure,
            check_reversion_safety,
            update_override_status,
            record_override_extension,
        ],
    )

    print(f"Worker connected to {temporal_address}, listening on queue 'network-changes'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
