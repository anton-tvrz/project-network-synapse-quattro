"""Workflow for detecting and remediating configuration drift.

Compares the Infrahub intended config against the device running config,
classifies drift severity, and auto-remediates when drift is detected.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from network_synapse.scripts.generate_configs import generate_interface_config
    from synapse_workers.activities.config_deployment_activities import deploy_config
    from synapse_workers.activities.device_backup_activities import backup_running_config, store_backup
    from synapse_workers.activities.drift_activities import fetch_running_config, log_audit_event
    from synapse_workers.activities.infrahub_activities import fetch_device_config, update_device_status
    from synapse_workers.activities.validation_activities import validate_bgp, validate_interfaces


class DriftSeverity(enum.StrEnum):
    """Classification of detected drift."""

    NONE = "none"
    COSMETIC = "cosmetic"
    CRITICAL = "critical"


@dataclass
class DriftResult:
    """Result of comparing intended vs running configuration."""

    has_drift: bool
    severity: DriftSeverity
    diff: str


def _has_admin_state_key(obj: object) -> bool:
    """Recursively check if a dict/list structure contains an 'admin-state' key."""
    if isinstance(obj, dict):
        if "admin-state" in obj:
            return True
        return any(_has_admin_state_key(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_admin_state_key(item) for item in obj)
    return False


def classify_drift(intended_json: str, running_json: str) -> DriftResult:
    """Compare intended and running configs and classify drift severity.

    This is a deterministic pure function — safe to call inside a workflow.
    """
    intended = json.loads(intended_json)
    running = json.loads(running_json)

    if intended == running:
        return DriftResult(has_drift=False, severity=DriftSeverity.NONE, diff="")

    # Build a human-readable diff of top-level differences
    diff_lines: list[str] = []
    all_keys = intended.keys() | running.keys()
    has_critical = False

    for key in sorted(all_keys):
        i_val = intended.get(key)
        r_val = running.get(key)
        if i_val != r_val:
            diff_lines.append(f"key={key} intended={json.dumps(i_val)} running={json.dumps(r_val)}")
            # Missing/added keys or admin-state changes are critical
            if i_val is None or r_val is None or _has_admin_state_key(r_val) or _has_admin_state_key(i_val):
                has_critical = True

    severity = DriftSeverity.CRITICAL if has_critical else DriftSeverity.COSMETIC
    return DriftResult(has_drift=True, severity=severity, diff="\n".join(diff_lines))


# Retry policy for device communication
device_retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)


@workflow.defn
class DriftRemediationWorkflow:
    """Detect config drift and remediate back to Infrahub intended state.

    Steps:
      1. Fetch intended config from Infrahub
      2. Generate intended SR Linux JSON from Infrahub data
      3. Fetch running config from device via gNMI GET
      4. Diff intended vs actual — classify drift severity
      5. If no drift: return early
      6. If drift: backup running config, re-deploy intended, validate
      7. Report drift event via audit log
    """

    @workflow.run
    async def run(self, device_hostname: str, ip_address: str) -> str:
        """Execute drift detection and remediation.

        Returns:
            "NO_DRIFT" if configs match, "REMEDIATED" if drift was fixed.

        Raises:
            ApplicationError: If remediation deployment or validation fails.
        """
        workflow.logger.info(f"Starting drift check for {device_hostname} ({ip_address})")

        # 1. Fetch intended config from Infrahub
        device_data = await workflow.execute_activity(
            fetch_device_config,
            args=[device_hostname],
            start_to_close_timeout=timedelta(seconds=30),
        )

        # 2. Generate intended SR Linux JSON config from Infrahub data
        # (deterministic — safe to run inside workflow)
        iface_payload = json.loads(generate_interface_config(device_data["interfaces"]))
        intended_config_json = json.dumps(iface_payload)

        # 3. Fetch running config from device
        running_config_json = await workflow.execute_activity(
            fetch_running_config,
            args=[device_hostname, ip_address],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=device_retry_policy,
        )

        # 4. Classify drift (deterministic — runs in workflow)
        drift = classify_drift(intended_config_json, running_config_json)

        if not drift.has_drift:
            workflow.logger.info(f"No drift detected on {device_hostname}")
            return "NO_DRIFT"

        # 5. Drift detected — log and remediate
        workflow.logger.warning(f"Drift detected on {device_hostname}: severity={drift.severity.value}\n{drift.diff}")

        await workflow.execute_activity(
            log_audit_event,
            args=["DRIFT_DETECTED", device_hostname, f"severity={drift.severity.value} diff={drift.diff}"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 6. Backup current (drifted) config before remediation
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

        # 7. Re-deploy intended config
        try:
            await workflow.execute_activity(
                deploy_config,
                args=[device_hostname, ip_address, intended_config_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Drift remediation deploy failed on {device_hostname}: {e!s}")
            await workflow.execute_activity(
                update_device_status,
                args=[device_hostname, "maintenance"],
                start_to_close_timeout=timedelta(seconds=10),
            )
            await workflow.execute_activity(
                log_audit_event,
                args=["DRIFT_REMEDIATION_FAILED", device_hostname, str(e)],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise ApplicationError(f"Drift remediation failed for {device_hostname}: {e!s}", non_retryable=True) from e

        # 8. Post-remediation validation
        try:
            await workflow.execute_activity(
                validate_bgp,
                args=[device_hostname, ip_address],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=device_retry_policy,
            )
            intended_ifaces = device_data.get("interfaces", {}).get("interfaces", [])
            await workflow.execute_activity(
                validate_interfaces,
                args=[device_hostname, ip_address, intended_ifaces],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Post-remediation validation failed on {device_hostname}: {e!s}")
            await workflow.execute_activity(
                update_device_status,
                args=[device_hostname, "maintenance"],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise ApplicationError(
                f"Drift remediation failed for {device_hostname}: validation error: {e!s}", non_retryable=True
            ) from e

        # 9. Success — update status and log
        await workflow.execute_activity(
            update_device_status,
            args=[device_hostname, "active"],
            start_to_close_timeout=timedelta(seconds=10),
        )
        await workflow.execute_activity(
            log_audit_event,
            args=["DRIFT_REMEDIATED", device_hostname, f"severity={drift.severity.value}"],
            start_to_close_timeout=timedelta(seconds=10),
        )

        workflow.logger.info(f"Drift remediated on {device_hostname}")
        return "REMEDIATED"
