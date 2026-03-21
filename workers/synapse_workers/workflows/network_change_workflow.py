"""Workflow for standard network configuration changes."""

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import activity definitions for registration
with workflow.unsafe.imports_passed_through():
    from network_synapse.scripts.generate_configs import generate_bgp_config, generate_interface_config
    from network_synapse.scripts.hygiene_checker import run_hygiene_checks
    from synapse_workers.activities.config_deployment_activities import deploy_config, rollback_config
    from synapse_workers.activities.device_backup_activities import backup_running_config, store_backup
    from synapse_workers.activities.infrahub_activities import fetch_device_config, update_device_status
    from synapse_workers.activities.validation_activities import validate_bgp, validate_interfaces

# Standard retry policy for device communication
device_retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)


@workflow.defn
class NetworkChangeWorkflow:
    """Standard network change: backup -> generate config -> deploy -> validate."""

    @workflow.run
    async def run(self, device_hostname: str, ip_address: str) -> str:
        workflow.logger.info(f"Starting NetworkChangeWorkflow for {device_hostname}")

        # 1. Backup current running config
        workflow.logger.info("Executing Step 1: Backup")
        backup_json = await workflow.execute_activity(
            backup_running_config,
            args=[device_hostname, ip_address],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=device_retry_policy,
        )

        await workflow.execute_activity(
            store_backup,
            args=[device_hostname, backup_json],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 2. Fetch intended config from Infrahub
        workflow.logger.info("Executing Step 2: Fetch Intention")
        device_data = await workflow.execute_activity(
            fetch_device_config,
            args=[device_hostname],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # 3. Generate SR Linux JSON config (deterministic local execution inside workflow)
        # We merge the base BGP and Interface configs into a single SR Linux structured JSON body
        workflow.logger.info("Executing Step 3: Generate Config")
        try:
            _bgp_payload = json.loads(generate_bgp_config(device_data["bgp"]))
            iface_payload = json.loads(generate_interface_config(device_data["interfaces"]))

            # SR Linux accepts a merged dictionary structure at the root level `/`
            # For simplicity in this MVP, we will only deploy the interface payload first
            # to verify basic gNMI reachability and application.
            # TODO: Properly assemble the merged `/` object for both.
            intended_config_json = json.dumps(iface_payload)

        except Exception as e:
            workflow.logger.error(f"Template rendering failed: {e!s}")
            raise

        # 4. Pre-deployment Hygiene check
        workflow.logger.info("Executing Step 4: Hygiene Checks")
        passes_hygiene = run_hygiene_checks(json.dumps(_bgp_payload), intended_config_json)
        if not passes_hygiene:
            # Mark deployment as failed in Infrahub, no rollback needed since we didn't push
            await workflow.execute_activity(
                update_device_status,
                args=[device_hostname, "maintenance"],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise RuntimeError("Deployment aborted due to Hygiene Checker failures.")

        # 5. Deploy config via gNMI
        workflow.logger.info("Executing Step 5: Deploy Config")
        try:
            await workflow.execute_activity(
                deploy_config,
                args=[device_hostname, ip_address, intended_config_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Deployment failed! Initiating rollback: {e!s}")

            # 6. Rollback on failure
            await workflow.execute_activity(
                rollback_config,
                args=[device_hostname, ip_address, backup_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )

            # Mark deployment as failed in Infrahub
            await workflow.execute_activity(
                update_device_status,
                args=[device_hostname, "maintenance"],
                start_to_close_timeout=timedelta(seconds=10),
            )

            raise RuntimeError(f"Deployment failed and rolled back: {e!s}") from e

        # 7. Post-deployment validation
        workflow.logger.info("Executing Step 7: Post-deployment Validation")
        try:
            await workflow.execute_activity(
                validate_bgp,
                args=[device_hostname, ip_address],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=device_retry_policy,
            )

            intended_ifaces = device_data["interfaces"]["interfaces"]
            await workflow.execute_activity(
                validate_interfaces,
                args=[device_hostname, ip_address, intended_ifaces],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Post-deployment validation failed: {e!s}")
            # Rollback since validation failed
            await workflow.execute_activity(
                rollback_config,
                args=[device_hostname, ip_address, backup_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
            await workflow.execute_activity(
                update_device_status,
                args=[device_hostname, "maintenance"],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise RuntimeError(f"Validation failed, rolled back: {e!s}") from e

        # Success!
        await workflow.execute_activity(
            update_device_status,
            args=[device_hostname, "active"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        workflow.logger.info(f"Successfully completed network change for {device_hostname}")
        return "SUCCESS"
