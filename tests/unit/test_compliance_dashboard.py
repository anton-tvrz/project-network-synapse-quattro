"""Unit tests for the Compliance Tracking dashboard trend panel (Issue #71).

Validates the Grafana InfluxDB datasource provisioning and the
"Intent Coverage Trend" panel, which charts lineage coverage over time
from the compliance_posture_fleet measurement written by the posture
writer (Issue #70).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

GRAFANA_DIR = Path(__file__).parents[2] / "development" / "grafana"
DATASOURCE_PATH = GRAFANA_DIR / "provisioning" / "datasources" / "influxdb.yml"
DASHBOARD_PATH = GRAFANA_DIR / "dashboards" / "compliance-tracking.json"

INFLUXDB_DATASOURCE_UID = "influxdb-compliance"


@pytest.fixture(scope="module")
def influx_datasource() -> dict:
    """The provisioned InfluxDB datasource definition."""
    assert DATASOURCE_PATH.exists(), f"{DATASOURCE_PATH} does not exist"
    config = yaml.safe_load(DATASOURCE_PATH.read_text())
    (datasource,) = config["datasources"]
    return datasource


@pytest.fixture(scope="module")
def trend_panel() -> dict:
    """The Intent Coverage Trend panel from the Compliance Tracking dashboard."""
    dashboard = json.loads(DASHBOARD_PATH.read_text())
    matches = [p for p in dashboard["panels"] if p.get("title") == "Intent Coverage Trend"]
    assert len(matches) == 1, "expected exactly one 'Intent Coverage Trend' panel"
    return matches[0]


@pytest.mark.unit
class TestInfluxDatasource:
    """Grafana provisioning for the InfluxDB compliance datasource."""

    def test_datasource_targets_compose_influxdb_service(self, influx_datasource: dict) -> None:
        """The datasource points at the influxdb service from docker-compose-deps.yml."""
        assert influx_datasource["type"] == "influxdb"
        assert influx_datasource["url"] == "http://influxdb:8086"

    def test_datasource_uid_is_stable_for_panel_references(self, influx_datasource: dict) -> None:
        """Panels reference the datasource by uid, so it must be pinned."""
        assert influx_datasource["uid"] == INFLUXDB_DATASOURCE_UID

    def test_datasource_uses_flux_against_compliance_bucket(self, influx_datasource: dict) -> None:
        """Queries use Flux against the org/bucket the posture writer targets."""
        json_data = influx_datasource["jsonData"]
        assert json_data["version"] == "Flux"
        assert json_data["organization"] == "synapse"
        assert json_data["defaultBucket"] == "compliance"

    def test_datasource_token_comes_from_environment(self, influx_datasource: dict) -> None:
        """The token is injected via env var, not hardcoded in the provisioning file."""
        assert influx_datasource["secureJsonData"]["token"] == "$INFLUXDB_TOKEN"  # noqa: S105


@pytest.mark.unit
class TestIntentCoverageTrendPanel:
    """The Intent Coverage Trend panel definition."""

    def test_panel_is_a_timeseries_on_the_influx_datasource(self, trend_panel: dict) -> None:
        """The trend renders as a timeseries bound to the InfluxDB datasource."""
        assert trend_panel["type"] == "timeseries"
        assert trend_panel["datasource"]["uid"] == INFLUXDB_DATASOURCE_UID

    def test_panel_queries_fleet_lineage_coverage(self, trend_panel: dict) -> None:
        """The Flux query reads lineage_coverage_ratio from compliance_posture_fleet."""
        (target,) = trend_panel["targets"]
        query = target["query"]
        assert 'r._measurement == "compliance_posture_fleet"' in query
        assert 'r._field == "lineage_coverage_ratio"' in query

    def test_panel_aggregates_daily_for_week_over_week_trend(self, trend_panel: dict) -> None:
        """Daily mean aggregation makes the week-over-week trend readable."""
        (target,) = trend_panel["targets"]
        assert "aggregateWindow(every: 1d, fn: mean" in target["query"]

    def test_panel_displays_ratio_as_percent(self, trend_panel: dict) -> None:
        """Coverage is a 0..1 ratio, displayed as a percentage."""
        assert trend_panel["fieldConfig"]["defaults"]["unit"] == "percentunit"

    def test_panel_marks_the_95_percent_alert_threshold(self, trend_panel: dict) -> None:
        """The panel shows the 0.95 threshold that LineageCoverageDrop alerts on."""
        steps = trend_panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
        assert any(step.get("value") == 0.95 for step in steps)
