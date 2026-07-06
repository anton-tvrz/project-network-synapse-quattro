# Measurement Architecture & Metric Catalogue

How Network Synapse Quattro measures itself: the monitoring stack, the five
metric domains, where every metric comes from, where it lands, and what alerts
on it.

## Monitoring Stack

| Component | Role | Where | Port |
|-----------|------|-------|------|
| **Prometheus** | Scrapes and stores operational metrics; evaluates alert rules | `development/docker-compose-deps.yml` | 9090 |
| **Alertmanager** | Routes alerts to Slack by severity | config in `development/prometheus/alertmanager.yml` | — |
| **InfluxDB 2.7** | Long-retention (90d) compliance posture time series | `development/docker-compose-deps.yml` | 8086 |
| **Grafana** | Dashboards over both Prometheus and InfluxDB | `development/docker-compose-deps.yml` | 3000 |
| **SuzieQ** | Device state polling (BGP, interfaces, routes) | *disabled — amd64-only image, broken on Apple Silicon* | 8530/8531 |
| **Worker /metrics** | prometheus_client endpoint on the Temporal worker | `workers/synapse_workers/metrics.py` | 9464 |

## Data Flow

```
                       ┌──────────────────────────────────────────────┐
                       │                  Grafana :3000               │
                       │   5 live dashboards + 2 planned (#66, #68)   │
                       └────────▲──────────────────────────▲──────────┘
                                │ PromQL                    │ Flux
                     ┌──────────┴──────────┐      ┌─────────┴─────────┐
   alert_rules.yml ─▶│  Prometheus :9090   │      │  InfluxDB :8086   │
   (13 rules)        └────▲────▲────▲──────┘      │  org: synapse     │
                          │    │    │             │  bucket:          │
        Alertmanager ◀────┘    │    │ scrape      │  compliance (90d) │
        → Slack           up{} │    │             └─────────▲─────────┘
                               │    │                       │ line protocol
                ┌──────────────┴┐  ┌┴──────────────────┐  ┌─┴──────────────────┐
                │ Infrahub :8000│  │ Temporal worker    │  │ compliance posture │
                │ Temporal :7233│  │ /metrics :9464     │  │ writer (hourly     │
                └───────────────┘  │ (intent lifecycle) │  │ cron, queries      │
                                   └────────────────────┘  │ Infrahub)          │
                                                            └────────────────────┘
```

Two storage paths, deliberately:

- **Prometheus** holds *operational* metrics — things that alert (worker
  saturation, deployment failures, drift). Sources are scraped.
- **InfluxDB** holds *posture* time series — slow-moving compliance ratios
  written hourly by `invoke backend.write-posture`
  (`backend/network_synapse/monitoring/compliance_posture.py`), kept 90 days
  for week-over-week trend panels.

## Metric Domains

### 1. Platform Health

Is the automation platform itself up and keeping pace?

| Metric | Type | Source | Status |
|--------|------|--------|--------|
| `up{job=~"infrahub\|temporal\|synapse_worker"}` | gauge | Prometheus scrape health | live |
| `temporal_worker_task_slots_available{worker_type}` | gauge | Temporal SDK worker metrics | live (Temporal-emitted) |
| `temporal_workflow_completed{status}` | counter | Temporal server | live (Temporal-emitted) |

### 2. Business Intent Lifecycle (Issue #62)

Connectivity intents moving through provision → validate → decommission.
Emitted by `workers/synapse_workers/metrics.py`, scraped via the
`synapse_worker` job. Metrics are emitted from **activities only** — never
workflow code, which Temporal replays and would double-count.

| Metric | Type | Emitted from | Status |
|--------|------|--------------|--------|
| `intent_connectivity_total{status}` | counter | deploy/rollback activities (`deployed`, `failed`, `rolled_back`, `rollback_failed`) | live |
| `intent_provisioning_duration_seconds` | histogram | `deploy_config` (gNMI SET timing) | live |
| `intent_binding_failures_total` | counter | `fetch_device_config` on Infrahub errors | live |
| `intent_orphaned_rules_count` | gauge | future hygiene emitter | contract only |
| `intent_lineage_completeness_ratio` | gauge | future intent workflows | contract only |
| `intent_decommission_age_days` | histogram | future decommission flow | contract only |

### 3. Operational Intent / Overrides (Issue #63 — planned)

Temporary operational overrides (maintenance windows, emergency changes) and
their auto-revert lifecycle. Blocked on the OperationalOverrideWorkflow.

| Metric | Type | Status |
|--------|------|--------|
| `override_active_count` | gauge | planned |
| `override_auto_revert_success_total` / `override_auto_revert_failure_total` | counters | planned |
| `override_mean_duration_seconds` | histogram | planned |
| `override_extension_count_total` | counter | planned |
| `override_state_validation_result` | gauge | planned |

The `OverrideRevertFailed` alert already references
`override_revert_failures_total`; align the final metric name with the alert
expression when implementing.

### 4. Compliance & Drift

Does deployed reality match intended state, and can we prove it over time?

| Metric | Type | Source | Sink | Status |
|--------|------|--------|------|--------|
| `compliance_posture` / `completeness` (tags: `environment`, `device_group`, `device`) | field | posture writer | InfluxDB | live |
| `compliance_posture` / `drift_score` | field | posture writer (when running config available) | InfluxDB | live |
| `compliance_posture_fleet` / `lineage_coverage_ratio` | field | posture writer | InfluxDB | live (stand-in, see below) |
| `drift_score{device}` | gauge | SuzieQ custom exporter (#74) | Prometheus | planned |
| `suzieq_last_poll_timestamp_seconds` | gauge | SuzieQ custom exporter (#74) | Prometheus | planned |
| `bgp_session_state`, `interface_state_changes_total`, `probe_success` | various | device probes / SuzieQ | Prometheus | planned |
| `hygiene_check_passed_total` / `hygiene_check_failed_total` | counters | hygiene checker | Prometheus | planned |

> **Lineage coverage stand-in:** `lineage_coverage_ratio` is currently derived
> from *modeling completeness* (6 components per device: ASN, router-id, mgmt
> IP, role, routed interface, BGP sessions). Once the intent schemas from the
> intent-model design are loaded into Infrahub, `compute_device_completeness`
> is replaced by a true intent-lineage query; the metric contract is unchanged.

### 5. Adoption / Golden Path (Issue #77 — planned)

Is the platform actually being used instead of worked around?

| Metric | Type | Status |
|--------|------|--------|
| `support_tickets_opened_total` | counter | planned |
| API consumer tracking (per-consumer request counters) | counter | planned |

## Dashboards

Provisioned from `development/grafana/dashboards/` (see
`provisioning/dashboards/dashboards.yml`). Grafana admin login: `admin` /
`synapse`.

| # | Dashboard | Focus | Status |
|---|-----------|-------|--------|
| 1 | Network Operations | BGP sessions, interface state, traffic, routes | live |
| 2 | Automation Pipeline | Workflow success rate, durations, activity failures, workers | live |
| 3 | Compliance Tracking | Hygiene pass rate, drift score, Intent Coverage Trend (InfluxDB) | live |
| 4 | System Health | CPU / memory / disk / network of the platform | live |
| 5 | Capacity Planning | 7-day utilisation trends, device count, workflow volume | live |
| 6 | Intent Lifecycle | Lineage coverage headline, intent outcomes, provisioning latency, binding failures, per-device drill-down | live |
| 7 | Operational Intent | Override activity from #63 metrics | planned (#68) |

Compliance Tracking and Intent Lifecycle mix two datasources: Prometheus for
worker/hygiene metrics and the `influxdb-compliance` datasource (Flux) for
posture data. The Intent Lifecycle drill-down shows per-device modeling
completeness until the intent schemas enable true forward/reverse lineage.

## Alert Rules Reference

Defined in `development/prometheus/alert_rules.yml` (13 rules), validated in
CI by `tests/unit/test_alert_rules.py`, routed by
`development/prometheus/alertmanager.yml`:
critical → `#network-synapse-critical` (immediate, repeat 1h, never muted);
warning → `#network-synapse-alerts` (batched 15m);
info → default channel.
Warning and info alerts are muted during the `maintenance-window` time
interval (Sunday 02:00–06:00 UTC by default), and a firing critical alert
inhibits warning/info alerts for the same instance.

| Alert | Severity | Fires when | Metric domain |
|-------|----------|------------|---------------|
| BGPSessionDown | critical | BGP peer not established for 2m | compliance & drift |
| NetworkDeviceUnreachable | critical | device probe fails for 1m | compliance & drift |
| InfrahubApiDown | critical | Infrahub probe fails for 2m | platform health |
| PlatformDown | critical | Infrahub or Temporal unscrapeable for 2m | platform health |
| OverrideRevertFailed | critical | any revert failure in 15m | operational intent |
| InterfaceFlapDetected | warning | >3 state changes in 5m, sustained | compliance & drift |
| TemporalWorkflowFailureRate | warning | >50% workflows failing over 10m | platform health |
| WorkerSaturation | warning | zero free workflow task slots for 5m | platform health |
| OrphanedRulesIncreasing | warning | `intent_orphaned_rules_count` rising over 1h | business intent |
| DriftScoreElevated | warning | `drift_score` > 0.2 for 10m | compliance & drift |
| LineageCoverageDrop | warning | `intent_lineage_completeness_ratio` < 0.95 for 15m | business intent |
| SuzieQStale | warning | no successful poll for ~20m | compliance & drift |
| HighSupportTicketRate | info | >5 tickets/day | adoption |

Several alerts reference metrics whose emitters are still planned (#63, #74,
#77) — they are the contract those implementations must satisfy, and they stay
silent until the metrics exist.

## Operating It

```bash
uv run invoke dev.deps                      # start Prometheus, InfluxDB, Grafana, Infrahub, Temporal
uv run invoke workers.start                 # worker; /metrics on :9464 (WORKER_METRICS_PORT, 0 disables)
uv run invoke backend.write-posture         # one posture write; --dry-run prints line protocol
# hourly posture cron:
# 0 * * * * cd /path/to/repo && uv run invoke backend.write-posture
```

Key environment variables: `WORKER_METRICS_PORT` (worker), `INFLUXDB_URL` /
`INFLUXDB_TOKEN` / `INFLUXDB_ORG` / `INFLUXDB_BUCKET` / `ENVIRONMENT`
(posture writer), `SLACK_WEBHOOK_URL` (Alertmanager).
