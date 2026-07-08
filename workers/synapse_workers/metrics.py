"""Prometheus metrics for the Temporal workers — intent lifecycle (Issue #62).

Defines the intent lifecycle metric contract and exposes it on a /metrics
HTTP endpoint started from the worker entry point (WORKER_METRICS_PORT,
default 9464, 0 to disable). Prometheus scrapes it via the
``synapse_worker`` job in development/prometheus/prometheus.yml.

Metrics are registered in a dedicated ``REGISTRY`` (not the
prometheus_client global default) so imports and tests stay isolated.

Emission sites today:
  - intent_connectivity_total: deploy/rollback activities
    (config_deployment_activities), labeled by outcome status
  - intent_provisioning_duration_seconds: deploy_config activity
  - intent_binding_failures_total: fetch_device_config activity

The remaining gauges/histograms (orphaned rules, lineage completeness,
decommission age) define the contract for the intent workflows and the
hygiene/posture logic that will emit them; the LineageCoverageDrop and
OrphanedRulesIncreasing alert rules already query these names.

NOTE: metrics are emitted from *activities* only — never from workflow
code, which Temporal replays and would double-count.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

REGISTRY = CollectorRegistry()

intent_connectivity_total = Counter(
    "intent_connectivity",
    "Connectivity intent deployments by outcome status",
    ["status"],
    registry=REGISTRY,
)

intent_provisioning_duration_seconds = Histogram(
    "intent_provisioning_duration_seconds",
    "Time to provision a connectivity intent onto a device (gNMI SET)",
    registry=REGISTRY,
)

intent_orphaned_rules_count = Gauge(
    "intent_orphaned_rules_count",
    "Deployed config rules with no owning intent (set by hygiene checks)",
    registry=REGISTRY,
)

intent_lineage_completeness_ratio = Gauge(
    "intent_lineage_completeness_ratio",
    "Fraction of deployed config traceable to an intent (0..1)",
    registry=REGISTRY,
)

intent_binding_failures_total = Counter(
    "intent_binding_failures",
    "Failures to bind an intent to device data from the source of truth",
    registry=REGISTRY,
)

intent_decommission_age_days = Histogram(
    "intent_decommission_age_days",
    "Age of intents at decommission time, in days",
    buckets=(1, 7, 30, 90, 180, 365, float("inf")),
    registry=REGISTRY,
)

# ---------------------------------------------------------------------------
# Operational intent metrics (Issue #63) — emitted by the override activities
# ---------------------------------------------------------------------------

override_active_count = Gauge(
    "override_active_count",
    "Operational overrides currently active on devices",
    registry=REGISTRY,
)

override_auto_revert_success_total = Counter(
    "override_auto_revert_success",
    "Overrides successfully auto-reverted to current SoT intent",
    registry=REGISTRY,
)

override_auto_revert_failure_total = Counter(
    "override_auto_revert_failure",
    "Overrides whose auto-revert failed (device stuck in exception state)",
    registry=REGISTRY,
)

override_mean_duration_seconds = Histogram(
    "override_mean_duration_seconds",
    "Time an override was active on the device, observed at revert",
    buckets=(60, 300, 900, 3600, 14400, 86400, 604800, float("inf")),
    registry=REGISTRY,
)

override_extension_count_total = Counter(
    "override_extension_count",
    "Window extensions granted on operational overrides",
    registry=REGISTRY,
)

override_state_validation_result = Gauge(
    "override_state_validation_result",
    "Latest reversion-safety validation result per device (1 pass, 0 fail)",
    ["device"],
    registry=REGISTRY,
)


def start_metrics_server(port: int) -> None:
    """Expose the worker registry on an HTTP /metrics endpoint."""
    start_http_server(port, registry=REGISTRY)
