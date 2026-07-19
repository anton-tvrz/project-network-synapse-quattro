"""Unit tests for the Collector telemetry stack (Issue #169).

Validates the static configuration that wires the NAF Collector block into
the dev dependency stack:

  - Suzieq poller + REST API services in development/docker-compose-deps.yml
    (re-enabled with platform: linux/amd64 for Rosetta on Apple Silicon)
  - gnmic streaming gNMI subscriptions (interfaces + BGP) exported to
    Prometheus with normalized device-name labels
  - Loki + Alloy syslog ingestion pipeline for SR Linux nodes
  - Prometheus scrape job and Grafana datasource wiring
  - Suzieq inventory in the modern sources/devices/auths/namespaces format
    using containerlab DNS names
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

DEVELOPMENT_DIR = Path(__file__).parents[2] / "development"
DEPS_COMPOSE_PATH = DEVELOPMENT_DIR / "docker-compose-deps.yml"
GNMIC_CONFIG_PATH = DEVELOPMENT_DIR / "gnmic" / "gnmic.yml"
SUZIEQ_INVENTORY_PATH = DEVELOPMENT_DIR / "suzieq" / "suzieq-inventory.yml"
SUZIEQ_CONFIG_PATH = DEVELOPMENT_DIR / "suzieq" / "suzieq-cfg.yml"
ALLOY_CONFIG_PATH = DEVELOPMENT_DIR / "alloy" / "config.alloy"
PROMETHEUS_CONFIG_PATH = DEVELOPMENT_DIR / "prometheus" / "prometheus.yml"
LOKI_DATASOURCE_PATH = DEVELOPMENT_DIR / "grafana" / "provisioning" / "datasources" / "loki.yml"

FABRIC_NODES = ("spine01", "leaf01", "leaf02")
CLAB_DNS_NAMES = tuple(f"clab-spine-leaf-lab-{node}" for node in FABRIC_NODES)


@pytest.fixture(scope="module")
def deps_compose() -> dict:
    """Parsed docker-compose-deps.yml content."""
    assert DEPS_COMPOSE_PATH.exists(), f"{DEPS_COMPOSE_PATH} does not exist"
    return yaml.safe_load(DEPS_COMPOSE_PATH.read_text())


@pytest.fixture(scope="module")
def services(deps_compose: dict) -> dict:
    return deps_compose["services"]


@pytest.fixture(scope="module")
def gnmic_config() -> dict:
    assert GNMIC_CONFIG_PATH.exists(), f"{GNMIC_CONFIG_PATH} does not exist"
    return yaml.safe_load(GNMIC_CONFIG_PATH.read_text())


# ---------------------------------------------------------------------------
# Suzieq poller + REST API
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuzieqServices:
    """Suzieq is part of the dev dependency stack again (was commented out)."""

    def test_poller_service_defined(self, services: dict):
        assert "suzieq-poller" in services

    def test_poller_runs_amd64_under_emulation(self, services: dict):
        """The upstream image is amd64-only; OrbStack runs it via Rosetta."""
        assert services["suzieq-poller"]["platform"] == "linux/amd64"

    def test_poller_mounts_inventory_readonly(self, services: dict):
        volumes = services["suzieq-poller"]["volumes"]
        assert any("suzieq-inventory.yml" in v and v.endswith(":ro") for v in volumes)

    def test_poller_entrypoint_uses_inventory(self, services: dict):
        """The image ENTRYPOINT is /bin/bash, which would interpret a plain
        `command` as a shell script — sq-poller must be the entrypoint."""
        entrypoint = services["suzieq-poller"]["entrypoint"]
        assert "sq-poller" in entrypoint
        assert "-I" in entrypoint

    def test_poller_attached_to_clab_network(self, services: dict):
        """The poller must reach SR Linux mgmt IPs on the containerlab bridge."""
        assert "clab" in services["suzieq-poller"]["networks"]

    def test_poller_restarts_until_lab_is_up(self, services: dict):
        """dev.deps may run before lab-deploy; the poller must retry, not die."""
        assert services["suzieq-poller"]["restart"] == "unless-stopped"

    def test_rest_service_defined(self, services: dict):
        assert "suzieq-rest" in services

    def test_rest_shares_parquet_volume_with_poller(self, services: dict):
        poller_parquet = [v for v in services["suzieq-poller"]["volumes"] if "suzieq_parquet" in v]
        rest_parquet = [v for v in services["suzieq-rest"]["volumes"] if "suzieq_parquet" in v]
        assert poller_parquet
        assert rest_parquet

    def test_rest_api_published_on_documented_port(self, services: dict):
        """docs/runbooks.md documents the REST API at localhost:8530."""
        ports = services["suzieq-rest"]["ports"]
        assert any("8530" in str(p) for p in ports)

    def test_parquet_volume_declared(self, deps_compose: dict):
        assert "suzieq_parquet" in deps_compose["volumes"]


@pytest.mark.unit
class TestSuzieqInventory:
    """Inventory uses the modern Suzieq format and containerlab DNS names."""

    @pytest.fixture(scope="class")
    def inventory(self) -> dict:
        assert SUZIEQ_INVENTORY_PATH.exists()
        return yaml.safe_load(SUZIEQ_INVENTORY_PATH.read_text())

    def test_has_all_modern_format_sections(self, inventory: dict):
        for section in ("sources", "devices", "auths", "namespaces"):
            assert section in inventory, f"missing inventory section: {section}"

    def test_hosts_use_clab_dns_names(self, inventory: dict):
        urls = [host["url"] for source in inventory["sources"] for host in source["hosts"]]
        for dns_name in CLAB_DNS_NAMES:
            assert any(dns_name in url for url in urls), f"{dns_name} not in inventory"

    def test_no_hardcoded_mgmt_ips(self, inventory: dict):
        assert "172.20.20." not in SUZIEQ_INVENTORY_PATH.read_text()

    def test_namespace_wires_source_device_auth(self, inventory: dict):
        namespace = inventory["namespaces"][0]
        source_names = {s["name"] for s in inventory["sources"]}
        device_names = {d["name"] for d in inventory["devices"]}
        auth_names = {a["name"] for a in inventory["auths"]}
        assert namespace["source"] in source_names
        assert namespace["device"] in device_names
        assert namespace["auth"] in auth_names

    def test_suzieq_config_file_exists(self):
        """Shared poller/REST config (data dir, REST bind) is version-controlled."""
        assert SUZIEQ_CONFIG_PATH.exists()


# ---------------------------------------------------------------------------
# gnmic streaming telemetry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGnmicService:
    def test_service_defined(self, services: dict):
        assert "gnmic" in services

    def test_uses_multiarch_openconfig_image(self, services: dict):
        assert services["gnmic"]["image"].startswith("ghcr.io/openconfig/gnmic")

    def test_attached_to_clab_network(self, services: dict):
        assert "clab" in services["gnmic"]["networks"]

    def test_scrapeable_from_default_network(self, services: dict):
        """Prometheus scrapes gnmic over the compose default network."""
        assert "default" in services["gnmic"]["networks"]

    def test_mounts_config_readonly(self, services: dict):
        assert any("gnmic.yml" in v and v.endswith(":ro") for v in services["gnmic"]["volumes"])

    def test_runs_subscribe(self, services: dict):
        assert "subscribe" in services["gnmic"]["command"]


@pytest.mark.unit
class TestGnmicConfig:
    def test_targets_use_normalized_device_names(self, gnmic_config: dict):
        """Target keys are clean device names → the Prometheus `source` label
        carries `spine01`, not an address:port."""
        assert set(gnmic_config["targets"]) == set(FABRIC_NODES)

    def test_target_addresses_use_clab_dns(self, gnmic_config: dict):
        for node, target in gnmic_config["targets"].items():
            assert target["address"] == f"clab-spine-leaf-lab-{node}:57400"

    def test_subscribes_to_interface_oper_state(self, gnmic_config: dict):
        paths = [p for sub in gnmic_config["subscriptions"].values() for p in sub["paths"]]
        assert any("oper-state" in p and p.startswith("/interface") for p in paths)

    def test_subscribes_to_bgp_session_state(self, gnmic_config: dict):
        paths = [p for sub in gnmic_config["subscriptions"].values() for p in sub["paths"]]
        assert any("bgp" in p and "session-state" in p for p in paths)

    def test_bgp_subscription_is_on_change(self, gnmic_config: dict):
        bgp_subs = [sub for sub in gnmic_config["subscriptions"].values() if any("bgp" in p for p in sub["paths"])]
        assert bgp_subs
        assert all(sub["stream-mode"] == "on-change" for sub in bgp_subs)

    def test_prometheus_output_configured(self, gnmic_config: dict):
        outputs = gnmic_config["outputs"]
        prom_outputs = [o for o in outputs.values() if o["type"] == "prometheus"]
        assert len(prom_outputs) == 1
        assert prom_outputs[0]["listen"].endswith(":9273")

    def test_skip_verify_for_lab_tls(self, gnmic_config: dict):
        """containerlab SR Linux gNMI is TLS-only with self-signed certs."""
        assert gnmic_config["skip-verify"] is True

    def test_yang_module_prefixes_stripped_from_metric_names(self, gnmic_config: dict):
        """With json_ietf, SR Linux prefixes every path element with its YANG
        module (srl_nokia-interfaces:interface/...), which would leak into the
        Prometheus metric names. A processor strips them so the names the
        alert rules reference (gnmic_interface_state_interface_oper_state)
        stay vendor-neutral. Verified against a live SR Linux node."""
        processors = gnmic_config["processors"]
        strip = processors["strip-yang-prefixes"]["event-strings"]
        replace = strip["transforms"][0]["replace"]
        assert replace["apply-on"] == "name"
        assert "srl_nokia" in replace["old"]
        assert replace["new"] == ""

        prom_output = next(o for o in gnmic_config["outputs"].values() if o["type"] == "prometheus")
        assert "strip-yang-prefixes" in prom_output["event-processors"]


@pytest.mark.unit
class TestPrometheusScrapesGnmic:
    def test_gnmic_scrape_job_present(self):
        prometheus = yaml.safe_load(PROMETHEUS_CONFIG_PATH.read_text())
        jobs = {job["job_name"]: job for job in prometheus["scrape_configs"]}
        assert "gnmic" in jobs
        targets = [t for sc in jobs["gnmic"]["static_configs"] for t in sc["targets"]]
        assert "gnmic:9273" in targets


# ---------------------------------------------------------------------------
# Syslog ingestion (Loki + Alloy)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyslogPipeline:
    def test_loki_service_defined(self, services: dict):
        assert "loki" in services

    def test_alloy_service_defined(self, services: dict):
        assert "alloy" in services

    def test_alloy_publishes_syslog_udp_on_host(self, services: dict):
        """SR Linux nodes reach the host at 172.20.20.1 (clab gateway); the
        syslog listener must be published on the host, not just in-network."""
        ports = [str(p) for p in services["alloy"]["ports"]]
        assert any("5514" in p and p.endswith("/udp") for p in ports)

    def test_alloy_mounts_config_readonly(self, services: dict):
        assert any("config.alloy" in v and v.endswith(":ro") for v in services["alloy"]["volumes"])

    def test_alloy_config_listens_for_rfc5424_udp_syslog(self):
        """SR Linux emits RSYSLOG_SyslogProtocol23Format (RFC5424-style) —
        verified from the rsyslog config it generates on the device. An
        rfc3164 listener drops every message with a parse error."""
        config = ALLOY_CONFIG_PATH.read_text()
        assert "loki.source.syslog" in config
        assert '"udp"' in config
        assert '"5514"' in config or ":5514" in config
        settings = [line for line in config.splitlines() if "syslog_format" in line]
        assert settings
        assert all('"rfc5424"' in line for line in settings)

    def test_alloy_config_normalizes_device_label(self):
        """Syslog hostname is relabeled to the `device` label used by the
        rest of the observability stack."""
        config = ALLOY_CONFIG_PATH.read_text()
        assert "__syslog_message_hostname" in config
        assert '"device"' in config

    def test_alloy_writes_to_loki(self):
        config = ALLOY_CONFIG_PATH.read_text()
        assert "loki.write" in config
        assert "http://loki:3100/loki/api/v1/push" in config

    def test_grafana_has_loki_datasource(self):
        assert LOKI_DATASOURCE_PATH.exists()
        datasources = yaml.safe_load(LOKI_DATASOURCE_PATH.read_text())["datasources"]
        loki = [ds for ds in datasources if ds["type"] == "loki"]
        assert loki
        assert loki[0]["url"] == "http://loki:3100"

    def test_loki_volume_declared(self, deps_compose: dict):
        assert "loki_data" in deps_compose["volumes"]


# ---------------------------------------------------------------------------
# Compose-level wiring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComposeNetworks:
    def test_clab_network_is_external(self, deps_compose: dict):
        """The containerlab management bridge is owned by containerlab (or
        pre-created by invoke dev.deps), never by compose."""
        clab = deps_compose["networks"]["clab"]
        assert clab["external"] is True

    def test_no_service_left_commented_out(self):
        """The old commented-out suzieq block must be gone, not duplicated."""
        text = DEPS_COMPOSE_PATH.read_text()
        assert "# suzieq:" not in text
