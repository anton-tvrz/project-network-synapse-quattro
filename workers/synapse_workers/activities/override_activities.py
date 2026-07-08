"""Temporal activities for the OperationalOverrideWorkflow (Issues #48, #63).

Applies and reverts time-bounded operational overrides via gNMI, keeps the
OperationalOverride lifecycle status in Infrahub current, and emits the
operational intent metrics. Metrics are emitted here (activities) only —
never from workflow code, which Temporal replays and would double-count.

Metric ownership per outcome:
  - apply_override_config: override_active_count (inc on success)
  - revert_override_config: success counter, duration histogram, gauge dec —
    on its *success* path only; a failed revert raises without emitting so
    Temporal can retry without double-counting
  - record_override_revert_failure: failure counter + gauge dec, called by
    the workflow exactly once when the revert is abandoned
  - check_reversion_safety: override_state_validation_result per device
  - record_override_extension: extension counter
"""

from __future__ import annotations

import os

from temporalio import activity

from network_synapse.infrahub.client import InfrahubConfigClient
from network_synapse.scripts.validate_state import check_bgp_summary
from synapse_workers.activities._gnmi_io import deploy_config_via_gnmi
from synapse_workers.metrics import (
    override_active_count,
    override_auto_revert_failure_total,
    override_auto_revert_success_total,
    override_extension_count_total,
    override_mean_duration_seconds,
    override_state_validation_result,
)

# TODO: Add device credential management (env vars or vault)
# For MVP, we will use Containerlab default SR Linux credentials
DEFAULT_USER = "admin"
DEFAULT_PASS = "NokiaSrl1!"  # noqa: S105


@activity.defn
async def apply_override_config(device_hostname: str, ip_address: str, override_config_json: str) -> bool:
    """Apply the override config to a device via gNMI SET.

    On success the override becomes active on the device, so the active
    gauge is incremented here.
    """
    activity.logger.info(f"Applying override config to {device_hostname} at {ip_address}")

    result = await deploy_config_via_gnmi(
        device_hostname=device_hostname,
        ip_address=ip_address,
        config_payload=override_config_json,
        username=DEFAULT_USER,
        password=DEFAULT_PASS,
    )

    if not result:
        raise RuntimeError(f"Override apply failed for {device_hostname}")

    override_active_count.inc()
    return True


@activity.defn
async def revert_override_config(
    device_hostname: str,
    ip_address: str,
    intended_config_json: str,
    active_seconds: float,
) -> bool:
    """Converge the device back to *current* SoT intent (agreed in #161).

    Args:
        device_hostname: Device to revert.
        ip_address: Device management IP for gNMI.
        intended_config_json: Rendered config from the current SoT intent —
            not the pre-override snapshot, which is audit/manual fallback only.
        active_seconds: How long the override was active (workflow-computed,
            deterministic), observed into the duration histogram on success.

    Raises:
        RuntimeError: If the gNMI SET fails. No metrics are emitted on
            failure — the workflow records the final outcome via
            record_override_revert_failure once retries are exhausted.
    """
    activity.logger.info(f"Reverting override on {device_hostname}: converging to current SoT intent")

    result = await deploy_config_via_gnmi(
        device_hostname=device_hostname,
        ip_address=ip_address,
        config_payload=intended_config_json,
        username=DEFAULT_USER,
        password=DEFAULT_PASS,
    )

    if not result:
        raise RuntimeError(f"Override revert failed for {device_hostname}. Device may be stuck in exception state!")

    override_active_count.dec()
    override_auto_revert_success_total.inc()
    override_mean_duration_seconds.observe(active_seconds)
    return True


@activity.defn
async def record_override_revert_failure(device_hostname: str, reason: str) -> None:
    """Record a permanently failed auto-revert (override enters revert_failed).

    Called by the workflow exactly once when a revert is abandoned — either
    the safety check said no or the revert deploy exhausted its retries.
    """
    activity.logger.error(f"Override auto-revert failed on {device_hostname}: {reason}")
    override_active_count.dec()
    override_auto_revert_failure_total.inc()


@activity.defn
async def check_reversion_safety(device_hostname: str, ip_address: str) -> bool:
    """Validate the device is safe to converge back to intent.

    Checks BGP sessions are established before reverting. Returns the
    verdict (it does not raise on unsafe — that is a workflow decision)
    and records it in the per-device state validation gauge.
    """
    activity.logger.info(f"Checking reversion safety on {device_hostname} ({ip_address})")
    safe = bool(check_bgp_summary(ip_address))
    override_state_validation_result.labels(device=device_hostname).set(1 if safe else 0)
    if not safe:
        activity.logger.warning(f"Reversion safety check failed on {device_hostname}: BGP sessions not established")
    return safe


@activity.defn
async def update_override_status(override_name: str, status: str) -> None:
    """Update the OperationalOverride lifecycle status in Infrahub.

    Args:
        override_name: Unique name of the OperationalOverride node.
        status: Target status (pending, active, reverted, revert_failed,
            cancelled).

    Raises:
        ValueError: If status is invalid (non-retryable).
        RuntimeError: If the override is missing or Infrahub errors
            (retryable by Temporal).
    """
    client = InfrahubConfigClient(
        url=os.getenv("INFRAHUB_URL", "http://localhost:8000"),
        token=os.getenv("INFRAHUB_TOKEN", ""),
    )
    try:
        previous = client.update_override_status(override_name, status)
        activity.logger.info(
            "Override status updated: override=%s old_status=%s new_status=%s",
            override_name,
            previous,
            status,
        )
    finally:
        client.close()


@activity.defn
async def record_override_extension(override_name: str, additional_seconds: int) -> None:
    """Record a window extension granted on an operational override."""
    activity.logger.info(f"Override {override_name} window extended by {additional_seconds}s")
    override_extension_count_total.inc()
