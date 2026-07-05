"""Unit tests for the Prometheus alert rules file (Issue #80).

Validates development/prometheus/alert_rules.yml against the alert
specification from Epic E: all 8 alert conditions present, correct
severities, and well-formed rule structure (expr, labels, annotations).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ALERT_RULES_PATH = Path(__file__).parents[2] / "development" / "prometheus" / "alert_rules.yml"

# Alert name -> required severity, per Issue #80
EXPECTED_ALERTS = {
    "PlatformDown": "critical",
    "WorkerSaturation": "warning",
    "OverrideRevertFailed": "critical",
    "OrphanedRulesIncreasing": "warning",
    "DriftScoreElevated": "warning",
    "LineageCoverageDrop": "warning",
    "SuzieQStale": "warning",
    "HighSupportTicketRate": "info",
}


@pytest.fixture(scope="module")
def alert_rules() -> dict:
    """Parsed alert_rules.yml content."""
    assert ALERT_RULES_PATH.exists(), f"{ALERT_RULES_PATH} does not exist"
    return yaml.safe_load(ALERT_RULES_PATH.read_text())


@pytest.fixture(scope="module")
def rules_by_name(alert_rules: dict) -> dict[str, dict]:
    """All alerting rules across groups, keyed by alert name."""
    rules = {}
    for group in alert_rules.get("groups", []):
        for rule in group.get("rules", []):
            if "alert" in rule:
                rules[rule["alert"]] = rule
    return rules


@pytest.mark.unit
class TestAlertRulesFile:
    def test_file_has_at_least_one_group(self, alert_rules: dict) -> None:
        groups = alert_rules.get("groups")
        assert isinstance(groups, list)
        assert len(groups) >= 1

    def test_every_group_has_name_and_rules(self, alert_rules: dict) -> None:
        for group in alert_rules["groups"]:
            assert group.get("name"), f"group missing name: {group}"
            assert isinstance(group.get("rules"), list)
            assert len(group["rules"]) >= 1


@pytest.mark.unit
class TestAlertConditions:
    def test_all_eight_alerts_present(self, rules_by_name: dict) -> None:
        """The 8 Epic E alerts must exist alongside the pre-existing device alerts."""
        missing = set(EXPECTED_ALERTS) - set(rules_by_name)
        assert not missing, f"missing alerts: {sorted(missing)}"

    def test_every_rule_in_file_is_well_formed(self, rules_by_name: dict) -> None:
        """All rules (including pre-existing ones) have expr, valid severity, and annotations."""
        for name, rule in rules_by_name.items():
            assert str(rule.get("expr", "")).strip(), f"{name}: empty expr"
            assert rule.get("labels", {}).get("severity") in ("critical", "warning", "info"), (
                f"{name}: invalid severity"
            )
            assert rule.get("annotations", {}).get("summary"), f"{name}: missing summary"

    @pytest.mark.parametrize(("alert_name", "severity"), sorted(EXPECTED_ALERTS.items()))
    def test_alert_has_expected_severity(self, rules_by_name: dict, alert_name: str, severity: str) -> None:
        rule = rules_by_name[alert_name]
        assert rule.get("labels", {}).get("severity") == severity

    @pytest.mark.parametrize("alert_name", sorted(EXPECTED_ALERTS))
    def test_alert_has_nonempty_expr(self, rules_by_name: dict, alert_name: str) -> None:
        expr = rules_by_name[alert_name].get("expr")
        assert isinstance(expr, str)
        assert expr.strip()

    @pytest.mark.parametrize("alert_name", sorted(EXPECTED_ALERTS))
    def test_alert_has_summary_and_description(self, rules_by_name: dict, alert_name: str) -> None:
        annotations = rules_by_name[alert_name].get("annotations", {})
        assert annotations.get("summary"), f"{alert_name} missing annotations.summary"
        assert annotations.get("description"), f"{alert_name} missing annotations.description"

    def test_critical_alerts_fire_quickly(self, rules_by_name: dict) -> None:
        """Critical alerts must not sit in pending state longer than 5 minutes."""
        for name, severity in EXPECTED_ALERTS.items():
            if severity != "critical":
                continue
            for_duration = rules_by_name[name].get("for", "0s")
            value, unit = int(for_duration[:-1]), for_duration[-1]
            assert unit in ("s", "m"), f"{name}: unexpected 'for' unit {unit}"
            assert (value if unit == "s" else value * 60) <= 300, f"{name}: 'for' too slow for critical"
