"""Temporal worker entry point."""

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from synapse_workers.activities.config_deployment_activities import deploy_config, rollback_config
from synapse_workers.activities.device_backup_activities import backup_running_config, store_backup
from synapse_workers.activities.infrahub_activities import fetch_device_config, update_device_status
from synapse_workers.activities.validation_activities import validate_bgp, validate_interfaces
from synapse_workers.workflows.drift_remediation_workflow import DriftRemediationWorkflow
from synapse_workers.workflows.emergency_change_workflow import EmergencyChangeWorkflow
from synapse_workers.workflows.network_change_workflow import NetworkChangeWorkflow


async def main() -> None:
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(temporal_address)

    worker = Worker(
        client,
        task_queue="network-changes",
        workflows=[
            NetworkChangeWorkflow,
            DriftRemediationWorkflow,
            EmergencyChangeWorkflow,
        ],
        activities=[
            backup_running_config,
            store_backup,
            fetch_device_config,
            update_device_status,
            deploy_config,
            rollback_config,
            validate_bgp,
            validate_interfaces,
        ],
    )

    print(f"Worker connected to {temporal_address}, listening on queue 'network-changes'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
