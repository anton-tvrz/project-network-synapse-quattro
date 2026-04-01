"""Workflow for emergency network changes with expedited approval.

Skips change windows and hygiene checks. Includes full audit trail,
optional time-bounded auto-reversion via Temporal timer, and rollback
on failure.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from synapse_workers.activities.config_deployment_activities import deploy_config, rollback_config
    from synapse_workers.activities.device_backup_activities import backup_running_config, store_backup
    from synapse_workers.activities.drift_activities import log_audit_event
    from synapse_workers.activities.infrahub_activities import update_device_status
    from synapse_workers.activities.validation_activities import validate_bgp


# Retry policy for device communication
device_retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)


@dataclasses.dataclass
class EmergencyChangeInput:
    """Input for an emergency change workflow execution."""

    device_hostname: str
    ip_address: str
    config_json: str
    reason: str
    operator: str
    ttl_seconds: int = 0  # 0 = permanent, >0 = auto-revert after N seconds


@workflow.defn
class EmergencyChangeWorkflow:
    """Emergency change: skip change window, fast-track with audit trail.

    Steps:
      1. Log emergency initiation (operator, reason, timestamp)
      2. Backup current running config
      3. Deploy emergency config via gNMI (no hygiene check)
      4. Validate post-deploy state
      5. If ttl_seconds > 0: wait, then auto-revert to backup
      6. Full audit trail throughout
    """

    @workflow.run
    async def run(self, change_input: EmergencyChangeInput) -> str:
        """Execute emergency change.

        Returns:
            "EMERGENCY_APPLIED" if permanent, "EMERGENCY_REVERTED" if TTL expired.

        Raises:
            ApplicationError: If deploy or validation fails (after rollback).
        """
        device = change_input.device_hostname
        ip = change_input.ip_address

        workflow.logger.info(
            f"EMERGENCY CHANGE initiated for {device} by {change_input.operator}: {change_input.reason}"
        )

        # 1. Audit: log initiation
        await workflow.execute_activity(
            log_audit_event,
            args=["EMERGENCY_INITIATED", device, f"operator={change_input.operator} reason={change_input.reason}"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 2. Backup current config
        backup_json = await workflow.execute_activity(
            backup_running_config,
            args=[device, ip],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=device_retry_policy,
        )
        await workflow.execute_activity(
            store_backup,
            args=[device, backup_json],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 3. Mark device as emergency status
        await workflow.execute_activity(
            update_device_status,
            args=[device, "maintenance"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 4. Deploy emergency config (no hygiene — it's an emergency)
        try:
            await workflow.execute_activity(
                deploy_config,
                args=[device, ip, change_input.config_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Emergency deploy failed on {device}: {e!s}")
            await workflow.execute_activity(
                rollback_config,
                args=[device, ip, backup_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
            await workflow.execute_activity(
                log_audit_event,
                args=["EMERGENCY_DEPLOY_FAILED", device, str(e)],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise ApplicationError(f"Emergency deploy failed for {device}: {e!s}", non_retryable=True) from e

        # 5. Post-deploy validation
        try:
            await workflow.execute_activity(
                validate_bgp,
                args=[device, ip],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Emergency post-deploy validation failed on {device}: {e!s}")
            await workflow.execute_activity(
                rollback_config,
                args=[device, ip, backup_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
            await workflow.execute_activity(
                log_audit_event,
                args=["EMERGENCY_VALIDATION_FAILED", device, str(e)],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise ApplicationError(f"Emergency validation failed for {device}: {e!s}", non_retryable=True) from e

        await workflow.execute_activity(
            log_audit_event,
            args=["EMERGENCY_APPLIED", device, f"operator={change_input.operator} ttl={change_input.ttl_seconds}s"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 6. Time-bounded override: auto-revert after TTL
        if change_input.ttl_seconds > 0:
            workflow.logger.info(f"Emergency change on {device} will auto-revert in {change_input.ttl_seconds}s")
            await workflow.sleep(timedelta(seconds=change_input.ttl_seconds))

            workflow.logger.info(f"TTL expired for emergency change on {device}, reverting to backup")

            await workflow.execute_activity(
                rollback_config,
                args=[device, ip, backup_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
            await workflow.execute_activity(
                update_device_status,
                args=[device, "active"],
                start_to_close_timeout=timedelta(seconds=10),
            )
            await workflow.execute_activity(
                log_audit_event,
                args=["EMERGENCY_REVERTED", device, f"auto-reverted after {change_input.ttl_seconds}s TTL"],
                start_to_close_timeout=timedelta(seconds=10),
            )

            workflow.logger.info(f"Emergency change auto-reverted on {device}")
            return "EMERGENCY_REVERTED"

        # Permanent emergency change
        await workflow.execute_activity(
            update_device_status,
            args=[device, "active"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        workflow.logger.info(f"Emergency change applied permanently on {device}")
        return "EMERGENCY_APPLIED"
