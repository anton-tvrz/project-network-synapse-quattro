"""Consistency tests between the SuzieQ exporter and its consumers (Issue #190).

Three separate places name the exporter's metrics, and until this issue none
of them agreed with the exporter itself:

  - ``development/prometheus/alert_rules.yml`` alerted on ``drift_score``
  - ``development/grafana/dashboards/compliance-tracking.json`` charted
    ``config_drift_score``
  - the exporter registers ``suzieq_drift_score``

A PromQL expression naming a metric that is never produced does not error —
it silently returns no data, so the alert never fires and the panel is blank
forever. Nothing failed; the observability was simply absent.

These tests derive the expected names from the exporter's own registry, so a
future rename breaks the build instead of quietly disabling an alert.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

DEVELOPMENT_DIR = Path(__file__).parents[2] / "development"
ALERT_RULES_PATH = DEVELOPMENT_DIR / "prometheus" / "alert_rules.yml"
PROMETHEUS_CONFIG_PATH = DEVELOPMENT_DIR / "prometheus" / "prometheus.yml"
COMPLIANCE_DASHBOARD_PATH = DEVELOPMENT_DIR / "grafana" / "dashboards" / "compliance-tracking.json"

EXPORTER_JOB = "suzieq_exporter"

# Prometheus identifiers appearing in an expression; used to spot references to
# suzieq_-prefixed metrics that the exporter does not actually register.
_IDENTIFIER = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b")
# Quoted label values (e.g. job="suzieq_exporter") are matcher operands, not
# metric names — strip them before scanning for metric identifiers.
_QUOTED = re.compile(r"""(['"]).*?\1""")


def _metric_names(expr: str) -> set[str]:
    """Metric identifiers referenced by a PromQL expression."""
    return set(_IDENTIFIER.findall(_QUOTED.sub("", expr)))


@pytest.fixture(scope="module")
def exported_metric_names() -> set[str]:
    """Every metric name the exporter registers, read from its own registry."""
    from network_synapse.collector import suzieq_drift

    names: set[str] = set()
    for metric in suzieq_drift.REGISTRY.collect():
        names.add(metric.name)
        # Gauges expose the bare name; counters would add _total, etc.
        for sample in metric.samples:
            names.add(sample.name)
    return names


@pytest.fixture(scope="module")
def alert_exprs() -> dict[str, str]:
    rules = yaml.safe_load(ALERT_RULES_PATH.read_text())
    return {
        rule["alert"]: rule["expr"]
        for group in rules.get("groups", [])
        for rule in group.get("rules", [])
        if "alert" in rule
    }


@pytest.fixture(scope="module")
def dashboard_exprs() -> list[str]:
    dashboard = json.loads(COMPLIANCE_DASHBOARD_PATH.read_text())
    return [
        target["expr"]
        for panel in dashboard.get("panels", [])
        for target in panel.get("targets", [])
        if "expr" in target
    ]


@pytest.fixture(scope="module")
def prometheus_config() -> dict:
    return yaml.safe_load(PROMETHEUS_CONFIG_PATH.read_text())


# ---------------------------------------------------------------------------
# The exporter must produce what the alerts consume
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExporterProducesConsumedMetrics:
    def test_exports_a_drift_score_metric(self, exported_metric_names: set[str]) -> None:
        assert "suzieq_drift_score" in exported_metric_names

    def test_exports_a_poll_freshness_metric(self, exported_metric_names: set[str]) -> None:
        """SuzieQStale alerts on poll age, so the exporter must publish it."""
        assert "suzieq_last_poll_timestamp_seconds" in exported_metric_names

    def test_every_suzieq_metric_in_alerts_is_exported(
        self, alert_exprs: dict[str, str], exported_metric_names: set[str]
    ) -> None:
        """No alert may reference a suzieq_ metric the exporter never emits."""
        unknown: dict[str, set[str]] = {}
        for alert, expr in alert_exprs.items():
            referenced = {token for token in _metric_names(expr) if token.startswith("suzieq_")}
            missing = referenced - exported_metric_names
            if missing:
                unknown[alert] = missing
        assert not unknown, f"alerts reference metrics the exporter does not export: {unknown}"

    def test_drift_alert_uses_the_exported_metric_name(self, alert_exprs: dict[str, str]) -> None:
        """Regression guard: this expr read ``drift_score`` and never fired."""
        assert "suzieq_drift_score" in alert_exprs["DriftScoreElevated"]

    def test_staleness_alert_uses_the_exported_metric_name(self, alert_exprs: dict[str, str]) -> None:
        assert "suzieq_last_poll_timestamp_seconds" in alert_exprs["SuzieQStale"]


# ---------------------------------------------------------------------------
# ... and what the dashboards chart
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDashboardUsesExportedMetrics:
    def test_compliance_drift_panel_uses_the_exported_metric_name(self, dashboard_exprs: list[str]) -> None:
        """Regression guard: this panel read ``config_drift_score`` — never populated."""
        drift_targets = [expr for expr in dashboard_exprs if "drift" in expr]
        assert drift_targets, "compliance dashboard has no drift panel"
        assert all("suzieq_drift_score" in expr for expr in drift_targets), drift_targets


# ---------------------------------------------------------------------------
# Scrape health
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScrapeHealth:
    def test_exporter_job_is_scraped(self, prometheus_config: dict) -> None:
        jobs = {job["job_name"] for job in prometheus_config["scrape_configs"]}
        assert EXPORTER_JOB in jobs

    def test_exporter_down_is_alerted(self, alert_exprs: dict[str, str]) -> None:
        """The exporter is a host process; if nobody starts it, say so loudly.

        Without this, an unstarted exporter is indistinguishable from a fabric
        with zero drift — every panel and alert built on it silently reads
        empty.
        """
        assert "SuzieqExporterDown" in alert_exprs
        expr = alert_exprs["SuzieqExporterDown"]
        assert EXPORTER_JOB in expr
        assert "up" in expr
