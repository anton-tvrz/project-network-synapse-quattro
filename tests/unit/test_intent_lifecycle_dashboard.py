"""Unit tests for the Intent Lifecycle Grafana dashboard (Issue #66).

Validates the dashboard definition against the issue spec: headline lineage
coverage, provisioning duration, binding failures, decommission age, and the
per-device lineage drill-down, sourced from both Prometheus (#62 worker
metrics) and InfluxDB (#70 posture data).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DASHBOARD_PATH = Path(__file__).parents[2] / "development" / "grafana" / "dashboards" / "intent-lifecycle.json"

INFLUXDB_DATASOURCE_UID = "influxdb-compliance"


@pytest.fixture(scope="module")
def dashboard() -> dict:
    """Parsed dashboard JSON."""
    assert DASHBOARD_PATH.exists(), f"{DASHBOARD_PATH} does not exist"
    return json.loads(DASHBOARD_PATH.read_text())


@pytest.fixture(scope="module")
def panels_by_title(dashboard: dict) -> dict[str, dict]:
    """Dashboard panels keyed by title."""
    return {p["title"]: p for p in dashboard["panels"]}


def _queries(panel: dict) -> str:
    """All target expressions/queries of a panel, concatenated."""
    return " ".join(t.get("expr", "") + t.get("query", "") for t in panel.get("targets", []))


@pytest.mark.unit
class TestDashboardShape:
    """Top-level dashboard identity and panel inventory."""

    def test_dashboard_has_stable_uid_and_title(self, dashboard: dict) -> None:
        """The dashboard is addressable at a fixed uid."""
        assert dashboard["uid"] == "intent-lifecycle"
        assert dashboard["title"] == "Intent Lifecycle"

    def test_all_five_spec_panels_present(self, panels_by_title: dict) -> None:
        """Every key panel from the Issue #66 spec exists."""
        expected = {
            "Lineage Coverage",
            "Intent Outcomes",
            "Provisioning Duration",
            "Binding Failures",
            "Decommission Age",
            "Per-Device Completeness (lineage drill-down)",
        }
        missing = expected - set(panels_by_title)
        assert not missing, f"missing panels: {sorted(missing)}"


@pytest.mark.unit
class TestHeadlinePanel:
    """The lineage coverage headline number."""

    def test_headline_is_a_stat_from_influxdb(self, panels_by_title: dict) -> None:
        """Coverage headline reads the fleet ratio from InfluxDB (live data)."""
        panel = panels_by_title["Lineage Coverage"]
        assert panel["type"] == "stat"
        assert panel["datasource"]["uid"] == INFLUXDB_DATASOURCE_UID
        assert 'r._field == "lineage_coverage_ratio"' in _queries(panel)

    def test_headline_shows_percent_with_alert_threshold(self, panels_by_title: dict) -> None:
        """Displayed as a percentage with the 0.95 LineageCoverageDrop threshold."""
        defaults = panels_by_title["Lineage Coverage"]["fieldConfig"]["defaults"]
        assert defaults["unit"] == "percentunit"
        assert any(s.get("value") == 0.95 for s in defaults["thresholds"]["steps"])


@pytest.mark.unit
class TestPrometheusPanels:
    """Panels charting the #62 worker metrics from Prometheus."""

    def test_intent_outcomes_charts_connectivity_by_status(self, panels_by_title: dict) -> None:
        """Outcome rates come from intent_connectivity_total grouped by status."""
        queries = _queries(panels_by_title["Intent Outcomes"])
        assert "intent_connectivity_total" in queries
        assert "status" in queries

    def test_provisioning_duration_uses_histogram_quantiles(self, panels_by_title: dict) -> None:
        """Duration panel shows quantiles over the provisioning histogram."""
        queries = _queries(panels_by_title["Provisioning Duration"])
        assert "histogram_quantile" in queries
        assert "intent_provisioning_duration_seconds_bucket" in queries

    def test_binding_failures_counts_recent_window(self, panels_by_title: dict) -> None:
        """Binding failures panel reads the #62 counter."""
        assert "intent_binding_failures_total" in _queries(panels_by_title["Binding Failures"])

    def test_decommission_age_reads_contract_histogram(self, panels_by_title: dict) -> None:
        """Decommission panel queries the (contract-only) age histogram."""
        assert "intent_decommission_age_days_bucket" in _queries(panels_by_title["Decommission Age"])


@pytest.mark.unit
class TestDrilldownPanel:
    """Per-device lineage drill-down (stand-in until intent schemas land)."""

    def test_drilldown_lists_per_device_completeness_from_influxdb(self, panels_by_title: dict) -> None:
        """Drill-down groups posture completeness by device from InfluxDB."""
        panel = panels_by_title["Per-Device Completeness (lineage drill-down)"]
        assert panel["datasource"]["uid"] == INFLUXDB_DATASOURCE_UID
        query = _queries(panel)
        assert 'r._measurement == "compliance_posture"' in query
        assert 'r._field == "completeness"' in query
