"""Unit tests for the Alertmanager configuration (Issue #157).

Validates maintenance-window suppression and inhibit rules: warnings and
info alerts are muted during the maintenance window, critical alerts always
page, and a firing critical alert inhibits downstream warnings for the same
instance.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONFIG_PATH = Path(__file__).parents[2] / "development" / "prometheus" / "alertmanager.yml"


@pytest.fixture(scope="module")
def config() -> dict:
    """Parsed alertmanager.yml."""
    return yaml.safe_load(CONFIG_PATH.read_text())


@pytest.fixture(scope="module")
def routes_by_severity(config: dict) -> dict[str, dict]:
    """Child routes keyed by the severity they match."""
    return {r["match"]["severity"]: r for r in config["route"]["routes"] if "severity" in r.get("match", {})}


@pytest.mark.unit
class TestMaintenanceWindow:
    """Mute time interval definition and wiring."""

    def test_maintenance_window_interval_is_defined(self, config: dict) -> None:
        """A named maintenance-window time interval exists."""
        names = [ti["name"] for ti in config.get("time_intervals", [])]
        assert "maintenance-window" in names

    def test_warning_route_is_muted_during_maintenance(self, routes_by_severity: dict) -> None:
        """Warning alerts are suppressed during the maintenance window."""
        assert routes_by_severity["warning"].get("mute_time_intervals") == ["maintenance-window"]

    def test_info_route_is_muted_during_maintenance(self, routes_by_severity: dict) -> None:
        """Info alerts are suppressed during the maintenance window."""
        assert routes_by_severity["info"].get("mute_time_intervals") == ["maintenance-window"]

    def test_critical_route_is_never_muted(self, routes_by_severity: dict) -> None:
        """Critical alerts must page even during maintenance."""
        assert "mute_time_intervals" not in routes_by_severity["critical"]

    def test_every_mute_reference_points_to_a_defined_interval(self, config: dict) -> None:
        """No route references an undefined time interval."""
        defined = {ti["name"] for ti in config.get("time_intervals", [])}
        for route in config["route"].get("routes", []):
            for ref in route.get("mute_time_intervals", []):
                assert ref in defined, f"route references undefined interval {ref!r}"


@pytest.mark.unit
class TestInhibitRules:
    """Critical alerts inhibit downstream noise for the same instance."""

    def test_critical_inhibits_warning_and_info_for_same_instance(self, config: dict) -> None:
        """A firing critical alert suppresses warning/info alerts sharing the instance."""
        rules = config.get("inhibit_rules", [])
        assert any(
            'severity="critical"' in " ".join(rule.get("source_matchers", []))
            and any("warning" in m and "info" in m for m in rule.get("target_matchers", []))
            and "instance" in rule.get("equal", [])
            for rule in rules
        ), "missing critical-inhibits-warning/info rule keyed on instance"


@pytest.mark.unit
class TestRouteConsistency:
    """Structural sanity of the routing tree."""

    def test_all_route_receivers_are_defined(self, config: dict) -> None:
        """The root and every child route point at a defined receiver."""
        defined = {r["name"] for r in config["receivers"]}
        assert config["route"]["receiver"] in defined
        for route in config["route"].get("routes", []):
            assert route["receiver"] in defined, f"undefined receiver {route['receiver']!r}"
