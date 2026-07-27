# Collector — Telemetry & Log Ingestion

The Collector block (NAF reference architecture) gathers operational state
from the containerlab fabric continuously, so network state is queryable
without manually running validation scripts. It complements the on-demand
gNMI GETs used by workflows (`validate_state.py`).

## Architecture

```
   containerlab fabric (SR Linux)               dev dependency stack
  ┌──────────────────────────────┐    ┌───────────────────────────────────┐
  │ spine01     leaf01    leaf02 │    │                                   │
  │   │ gNMI (TLS, :57400)  │    │◄───┤ gnmic ──────► Prometheus ► Grafana│
  │   │ SSH (:22)           │    │◄───┤ suzieq-poller ► parquet ► suzieq- │
  │   │ syslog (UDP)        │    │    │                           rest    │
  │   └──────► 172.20.20.1:5514 ─┼───►│ alloy ──────► Loki ─────► Grafana │
  └──────────────────────────────┘    └───────────────────────────────────┘
          `clab` docker network              `invoke dev.deps`
```

Three ingestion paths, all started by `uv run invoke dev.deps`:

| Path | Collector | Transport | Sink | Query via |
|------|-----------|-----------|------|-----------|
| Streaming telemetry | gnmic | gNMI subscribe (TLS) | Prometheus | PromQL / Grafana |
| Snapshot polling | Suzieq poller | SSH | Parquet | Suzieq REST API |
| Logs | Grafana Alloy | Syslog UDP (RFC5424) | Loki | LogQL / Grafana |

The collector containers join the external `clab` docker network to reach
the SR Linux management interfaces. `invoke dev.deps` pre-creates that
network when the lab hasn't been deployed yet (containerlab reuses an
existing network with a matching name), so `dev.deps` and `dev.lab-deploy`
work in either order. Collectors retry until the fabric appears.

## Streaming telemetry (gnmic)

`development/gnmic/gnmic.yml` subscribes to:

- `/interface[name=*]/oper-state` + octet/error counters — `sample` every 15s
- `/network-instance[name=*]/protocols/bgp/neighbor[peer-address=*]/session-state` — `on-change`

and re-exports everything on `gnmic:9273`, scraped by the Prometheus
service (job `gnmic`).

**Label normalization** (verified against a live SR Linux node):

- Targets are keyed by clean device names, so the `source` label carries
  `spine01`, not an `address:port` pair.
- A `strip-yang-prefixes` processor removes the YANG module prefixes that
  `json_ietf` puts into every path element (`srl_nokia-interfaces:...`),
  keeping metric names vendor-neutral.

Example queries:

```promql
# Interface state per device (1 = labelled state active)
gnmic_interface_state_interface_oper_state{source="spine01"}

# BGP sessions not established
gnmic_bgp_neighbor_state_network_instance_protocols_bgp_neighbor_session_state{session_state!="established"}

# Devices currently streaming (used by the NetworkDeviceUnreachable alert)
count(count by (source) (gnmic_interface_state_interface_oper_state))
```

The `NetworkDeviceUnreachable` alert fires when fewer than 3 devices are
present in the export: gnmic drops a device's series (60s expiration) when
its subscription dies.

## Snapshot polling (Suzieq)

The upstream `netenglabs/suzieq` image is amd64-only; it runs fine on Apple
Silicon under OrbStack's Rosetta emulation (`platform: linux/amd64`).

- `suzieq-poller` polls the fabric over SSH using
  `development/suzieq/suzieq-inventory.yml` (modern
  sources/devices/auths/namespaces format, containerlab DNS names, SR Linux
  polled as `devtype: linux`).
- `suzieq-rest` serves the collected parquet data:

```bash
curl -s "http://localhost:8530/api/v2/device/show?access_token=496157e6e869ef7f3d6ecb24a6f6d847b224ee4f"
curl -s "http://localhost:8530/api/v2/interface/show?access_token=496157e6e869ef7f3d6ecb24a6f6d847b224ee4f&namespace=spine-leaf-lab"
```

Both share `development/suzieq/suzieq-cfg.yml`. The API key is a static
dev-only value; the API is bound to localhost.

### Drift-score exporter (Issue #74)

SuzieQ runs its own state assertions (`/api/v2/{table}/assert`) — BGP sessions
established, interfaces up — against the collected snapshots. The
`suzieq_exporter` turns that pass/fail output into Prometheus drift metrics,
complementing the Infrahub-derived `compliance_posture` drift written to
InfluxDB.

- `backend/network_synapse/collector/suzieq_client.py` — the shared REST
  client (assert-table fetch, env-driven config); higher layers reuse it.
- `backend/network_synapse/collector/suzieq_drift.py` — scores each device as
  its fraction of failing assertions across the `bgp` and `interface` tables,
  and serves the gauges.

Metrics (dedicated registry, scraped by the `suzieq_exporter` Prometheus job
at `host.docker.internal:9275`):

| Metric | Meaning |
|--------|---------|
| `suzieq_drift_score{device}` | Fraction of failing SuzieQ assertions per device (0..1) |
| `suzieq_drift_score_aggregate` | Fleet-wide mean of the per-device scores (0..1) |
| `suzieq_last_poll_timestamp_seconds` | Unix time of the last successful collection (drives `SuzieQStale`) |

```bash
# Serve the exporter (refreshes every 60s, exposes :9275/metrics)
uv run invoke collector.suzieq-exporter

# One-shot look at the current scores without serving
uv run invoke collector.suzieq-exporter --dry-run
```

Configuration is env-driven (`SUZIEQ_REST_URL`, `SUZIEQ_API_TOKEN`,
`SUZIEQ_NAMESPACE`), defaulting to the dev stack. The exporter runs on the
host — the same pattern as the Temporal worker's metrics endpoint — so
Prometheus reaches it via `host.docker.internal`.

> **It is not started by `invoke dev.deps`.** Start it explicitly, as part of
> bring-up, alongside the worker and the portal. While it is down, the
> `suzieq_drift_score` series is simply absent, which in PromQL reads exactly
> like a fabric with zero drift: `DriftScoreElevated` cannot fire and the
> Compliance Tracking drift panel is blank. The `SuzieqExporterDown` alert
> (`up{job="suzieq_exporter"} == 0`) exists so this is loud rather than
> silent.

Example queries:

```promql
# Devices with any assert failures
suzieq_drift_score > 0

# Fleet drift trend
suzieq_drift_score_aggregate
```

## Syslog ingestion (Alloy → Loki)

SR Linux forwards syslog to the collector; Grafana Alloy listens on host
port `5514/udp` (RFC5424 — SR Linux emits RSYSLOG_SyslogProtocol23Format,
verified on-device), normalizes the header fields onto the stack's
label names (`device`, `severity`, `facility`, `app`), and pushes to Loki.
Loki is provisioned as a Grafana datasource.

Configure the fabric after deploying the lab:

```bash
uv run invoke dev.lab-syslog
# or: uv run python -m network_synapse.scripts.configure_syslog --device spine01
```

The script pushes `/system/logging/remote-server` (YANG-modelled JSON via
gNMI) pointing at `172.20.20.1:5514` — the clab bridge gateway, i.e. the
OrbStack host, where docker publishes the Alloy listener. Two details that
matter (verified against a live node):

- `network-instance: mgmt` — mgmt0 lives in the mgmt VRF; without it the
  packets are routed via the default network-instance and never arrive.
- facility `local6`, `match-above informational` — SR Linux logs all of its
  own subsystems at local6, mirroring the factory `buffer messages` filter.

Query in Grafana (Loki datasource) or via the API:

```logql
{job="srlinux-syslog", device="spine01"} |= "bgp"
```

## Resource footprint

~1.3GB on top of the existing stack (Suzieq poller 512M + REST 256M, gnmic
128M, Loki 256M, Alloy 128M) — see the budget comment in
`development/docker-compose-deps.yml`.
