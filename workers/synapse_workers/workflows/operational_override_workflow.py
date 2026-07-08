"""Workflow for time-bounded operational overrides (Issues #48, #49).

Applies a sanctioned deviation from as-built intent, waits on a durable
Temporal timer until the override window expires (or a signal arrives),
then converges the device back to the *current* SoT intent — not the
pre-override snapshot, which is captured for audit/manual fallback only
(agreed in #161).

Signals:
  - terminate_early(reason): incident resolved — revert now, mark cancelled
  - extend_window(additional_seconds, reason): incident ongoing — push
    end_time out and track the extension count
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from synapse_workers.activities.device_backup_activities import store_backup
    from synapse_workers.activities.drift_activities import (
        fetch_running_config,
        log_audit_event,
        render_intended_config,
    )
    from synapse_workers.activities.infrahub_activities import fetch_device_config
    from synapse_workers.activities.override_activities import (
        apply_override_config,
        check_reversion_safety,
        record_override_extension,
        record_override_revert_failure,
        revert_override_config,
        update_override_status,
    )


# Retry policy for device communication
device_retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)


@dataclasses.dataclass
class OperationalOverrideInput:
    """Input for an operational override workflow execution."""

    override_name: str
    device_hostname: str
    ip_address: str
    override_type: str  # admin_shutdown | maintenance_mode | traffic_drain | emergency_bypass
    override_config_json: str
    reason: str
    operator: str
    duration_seconds: int  # override window length; overrides are never open-ended


@workflow.defn
class OperationalOverrideWorkflow:
    """Apply a time-bounded override, wait, auto-revert to current intent.

    Steps (per Issue #48):
      1. capture_current_state — gNMI GET, stored for audit/manual fallback
      2. apply_override — gNMI SET with the override config
      3. update_infrahub — mark the OperationalOverride active
      4. wait_for_expiry_or_signal — durable timer, interruptible by signals
      5. check_reversion_safety — BGP sessions up before touching the device
      6. revert_to_original — converge to *current* SoT intent
      7. mark_completed — status reverted (expiry) or cancelled (early stop)
    """

    def __init__(self) -> None:
        self._terminated = False
        self._terminate_reason = ""
        self._pending_extensions: list[tuple[int, str]] = []

    @workflow.signal
    def terminate_early(self, reason: str) -> None:
        """Incident resolved — revert the override before the window expires."""
        workflow.logger.info(f"Early termination requested: {reason}")
        self._terminated = True
        self._terminate_reason = reason

    @workflow.signal
    def extend_window(self, additional_seconds: int, reason: str) -> None:
        """Incident ongoing — extend the override window."""
        if additional_seconds <= 0:
            workflow.logger.warning(f"Ignoring non-positive window extension: {additional_seconds}s ({reason})")
            return
        workflow.logger.info(f"Window extension requested: +{additional_seconds}s ({reason})")
        self._pending_extensions.append((additional_seconds, reason))

    @workflow.run
    async def run(self, override_input: OperationalOverrideInput) -> str:
        """Execute the override lifecycle.

        Returns:
            "OVERRIDE_REVERTED" if the window expired and auto-revert ran,
            "OVERRIDE_CANCELLED" if terminated early on request.

        Raises:
            ApplicationError: If the apply fails, the reversion safety check
                says no, or the revert fails (override enters revert_failed).
        """
        name = override_input.override_name
        device = override_input.device_hostname
        ip = override_input.ip_address

        if override_input.duration_seconds <= 0:
            raise ApplicationError(
                "duration_seconds must be > 0 — overrides are always time-bounded", non_retryable=True
            )

        workflow.logger.info(
            f"Override {name} ({override_input.override_type}) initiated for {device} "
            f"by {override_input.operator}: {override_input.reason}"
        )

        await workflow.execute_activity(
            log_audit_event,
            args=[
                "OVERRIDE_INITIATED",
                device,
                f"override={name} type={override_input.override_type} "
                f"operator={override_input.operator} reason={override_input.reason}",
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 1. Capture current state (OverrideAction.original_state — audit/manual fallback)
        original_state = await workflow.execute_activity(
            fetch_running_config,
            args=[device, ip],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=device_retry_policy,
        )
        await workflow.execute_activity(
            store_backup,
            args=[device, original_state],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=device_retry_policy,
        )

        # 2. Apply the override config
        try:
            await workflow.execute_activity(
                apply_override_config,
                args=[device, ip, override_input.override_config_json],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Override apply failed on {device}: {e!s}")
            try:
                await workflow.execute_activity(
                    log_audit_event,
                    args=["OVERRIDE_APPLY_FAILED", device, f"override={name} error={e!s}"],
                    start_to_close_timeout=timedelta(seconds=10),
                )
            except Exception as audit_exc:
                workflow.logger.error(f"Failed to audit OVERRIDE_APPLY_FAILED for {device}: {audit_exc!s}")
            raise ApplicationError(f"Override apply failed for {device}: {e!s}", non_retryable=True) from e

        # 3. Mark the override active in Infrahub
        await workflow.execute_activity(
            update_override_status,
            args=[name, "active"],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=device_retry_policy,
        )

        applied_at = workflow.now()
        end_time = applied_at + timedelta(seconds=override_input.duration_seconds)

        await workflow.execute_activity(
            log_audit_event,
            args=[
                "OVERRIDE_APPLIED",
                device,
                f"override={name} window={override_input.duration_seconds}s ends={end_time.isoformat()}",
            ],
            start_to_close_timeout=timedelta(seconds=10),
        )

        # 4. Wait for window expiry, early termination, or extension
        await self._wait_for_expiry_or_signal(name, device, end_time)

        early = self._terminated
        if early:
            await workflow.execute_activity(
                log_audit_event,
                args=["OVERRIDE_TERMINATED_EARLY", device, f"override={name} reason={self._terminate_reason}"],
                start_to_close_timeout=timedelta(seconds=10),
            )

        # 5. Reversion safety check — never converge a device that isn't healthy
        safe = await workflow.execute_activity(
            check_reversion_safety,
            args=[device, ip],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=device_retry_policy,
        )
        if not safe:
            workflow.logger.error(f"Reversion safety check failed on {device} — override {name} stuck")
            await self._mark_revert_failed(name, device, "reversion safety check failed")
            await workflow.execute_activity(
                log_audit_event,
                args=["OVERRIDE_REVERT_UNSAFE", device, f"override={name} safety check failed"],
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise ApplicationError(
                f"Override revert aborted for {device}: reversion safety check failed", non_retryable=True
            )

        # 6. Revert — converge to *current* SoT intent, not the snapshot (#161)
        device_data = await workflow.execute_activity(
            fetch_device_config,
            args=[device],
            start_to_close_timeout=timedelta(seconds=30),
        )
        intended_config_json = await workflow.execute_activity(
            render_intended_config,
            args=[device_data["interfaces"]],
            start_to_close_timeout=timedelta(seconds=10),
        )

        active_seconds = (workflow.now() - applied_at).total_seconds()
        try:
            await workflow.execute_activity(
                revert_override_config,
                args=[device, ip, intended_config_json, active_seconds],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=device_retry_policy,
            )
        except Exception as e:
            workflow.logger.error(f"Override revert failed on {device}: {e!s}")
            await self._mark_revert_failed(name, device, str(e))
            try:
                await workflow.execute_activity(
                    log_audit_event,
                    args=["OVERRIDE_REVERT_FAILED", device, f"override={name} error={e!s}"],
                    start_to_close_timeout=timedelta(seconds=10),
                )
            except Exception as audit_exc:
                workflow.logger.error(f"Failed to audit OVERRIDE_REVERT_FAILED for {device}: {audit_exc!s}")
            raise ApplicationError(f"Override revert failed for {device}: {e!s}", non_retryable=True) from e

        # 7. Mark completed. The device is already converged, so a status or
        # audit write failure is logged but never fails the workflow.
        final_status = "cancelled" if early else "reverted"
        try:
            await workflow.execute_activity(
                update_override_status,
                args=[name, final_status],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=device_retry_policy,
            )
        except Exception as status_exc:
            workflow.logger.error(f"Failed to mark override {name} {final_status} after revert: {status_exc!s}")
        try:
            await workflow.execute_activity(
                log_audit_event,
                args=[
                    "OVERRIDE_CANCELLED" if early else "OVERRIDE_REVERTED",
                    device,
                    f"override={name} active_seconds={active_seconds:.0f}",
                ],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=device_retry_policy,
            )
        except Exception as audit_exc:
            workflow.logger.error(f"Failed to audit override completion for {device}: {audit_exc!s}")

        workflow.logger.info(f"Override {name} {'cancelled early' if early else 'reverted'} on {device}")
        return "OVERRIDE_CANCELLED" if early else "OVERRIDE_REVERTED"

    async def _wait_for_expiry_or_signal(self, name: str, device: str, end_time: datetime) -> None:
        """Durable wait until end_time, processing extension/termination signals."""
        while not self._terminated:
            while self._pending_extensions:
                additional_seconds, extension_reason = self._pending_extensions.pop(0)
                end_time += timedelta(seconds=additional_seconds)
                await workflow.execute_activity(
                    record_override_extension,
                    args=[name, additional_seconds],
                    start_to_close_timeout=timedelta(seconds=10),
                )
                await workflow.execute_activity(
                    log_audit_event,
                    args=[
                        "OVERRIDE_EXTENDED",
                        device,
                        f"override={name} extended_by={additional_seconds}s "
                        f"ends={end_time.isoformat()} reason={extension_reason}",
                    ],
                    start_to_close_timeout=timedelta(seconds=10),
                )

            remaining = (end_time - workflow.now()).total_seconds()
            if remaining <= 0:
                workflow.logger.info(f"Override {name} window expired on {device}")
                break

            try:
                await workflow.wait_condition(
                    lambda: self._terminated or bool(self._pending_extensions),
                    timeout=timedelta(seconds=remaining),
                )
            except TimeoutError:
                # Timer fired — loop re-checks end_time in case an extension
                # landed in the same instant as the timeout.
                continue

    async def _mark_revert_failed(self, name: str, device: str, reason: str) -> None:
        """Record the failed revert (metrics) and set status revert_failed.

        Best-effort: the workflow is about to raise the real error, so
        bookkeeping failures are logged rather than masking it.
        """
        try:
            await workflow.execute_activity(
                record_override_revert_failure,
                args=[device, reason],
                start_to_close_timeout=timedelta(seconds=10),
            )
            await workflow.execute_activity(
                update_override_status,
                args=[name, "revert_failed"],
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=device_retry_policy,
            )
        except Exception as cleanup_exc:
            workflow.logger.error(f"Failed to record revert failure for {device}: {cleanup_exc!s}")
