"""Unit tests for the FirewallRuleSet schema (Issue #40).

Terminal object of the business intent chain (intent-model skill):

    ApplicationService -> ServiceEndpoint -> ConnectivityIntent
      -> InfrastructureBinding -> FirewallRuleSet
                                  ^^^^^^^^^^^^^^^ this file

This is the object an auditor points at. Everything above it exists so that
a rule found on a device can be walked back to the person who asked for it,
and so that a rule whose intent has been decommissioned can be found before
an auditor finds it.

The `binding` relationship is mandatory: a FirewallRuleSet with no
InfrastructureBinding is an orphan by construction, and making it impossible
to create one is cheaper than detecting it later.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCHEMA_PATH = Path(__file__).parents[2] / "backend" / "network_synapse" / "schemas" / "firewall_ruleset.yml"


@pytest.fixture(scope="module")
def nodes_by_kind() -> dict[str, dict]:
    assert SCHEMA_PATH.exists(), f"{SCHEMA_PATH} does not exist"
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    return {f"{n['namespace']}{n['name']}": n for n in schema.get("nodes", [])}


@pytest.fixture(scope="module")
def ruleset(nodes_by_kind: dict) -> dict:
    assert "FirewallRuleSet" in nodes_by_kind, f"kinds present: {sorted(nodes_by_kind)}"
    return nodes_by_kind["FirewallRuleSet"]


def _attributes(node: dict) -> dict[str, dict]:
    return {a["name"]: a for a in node.get("attributes", [])}


def _relationships(node: dict) -> dict[str, dict]:
    return {r["name"]: r for r in node.get("relationships", [])}


@pytest.mark.unit
class TestSchemaShape:
    def test_kind_is_defined(self, ruleset: dict) -> None:
        assert ruleset["namespace"] == "Firewall"
        assert ruleset["name"] == "RuleSet"

    def test_loads_after_connectivity_intent(self) -> None:
        """It references InfrastructureBinding, defined in connectivity_intent.yml."""
        from network_synapse.schemas.load_schemas import SCHEMA_LOAD_ORDER

        names = [Path(entry).name for entry in SCHEMA_LOAD_ORDER]
        assert "firewall_ruleset.yml" in names
        assert names.index("firewall_ruleset.yml") > names.index("connectivity_intent.yml")

    def test_avoids_deprecated_schema_keys(self, ruleset: dict) -> None:
        assert "display_labels" not in ruleset
        assert "default_filter" not in ruleset

    def test_declares_an_explicit_human_friendly_id(self, ruleset: dict) -> None:
        assert ruleset.get("human_friendly_id") == ["name__value"]


@pytest.mark.unit
class TestRuleContent:
    def test_action_is_permit_or_deny(self, ruleset: dict) -> None:
        attr = _attributes(ruleset)["action"]
        assert attr["kind"] == "Dropdown"
        assert {c["name"] for c in attr["choices"]} == {"permit", "deny"}

    def test_action_defaults_to_deny(self, ruleset: dict) -> None:
        """Fail closed. A rule created without an explicit action should not
        silently open traffic."""
        assert _attributes(ruleset)["action"]["default_value"] == "deny"

    @pytest.mark.parametrize("field", ["source_network", "destination_network"])
    def test_networks_are_validated_ip_networks(self, ruleset: dict, field: str) -> None:
        """IPNetwork rather than Text: a typo'd CIDR should fail at write
        time, not when the rule reaches a device."""
        assert _attributes(ruleset)[field]["kind"] == "IPNetwork"

    def test_has_a_rule_name_for_the_device(self, ruleset: dict) -> None:
        """The identifier the rule carries on the device, which is what a
        reverse lookup from a running config matches on."""
        assert "rule_name" in _attributes(ruleset)

    def test_has_service_ports(self, ruleset: dict) -> None:
        assert "service_ports" in _attributes(ruleset)

    def test_has_an_explicit_sequence(self, ruleset: dict) -> None:
        """Firewalls are first-match-wins, so ordering is part of the intent,
        not an implementation detail of whatever order rows come back in."""
        assert _attributes(ruleset)["sequence"]["kind"] == "Number"


@pytest.mark.unit
class TestLineage:
    def test_binding_is_mandatory(self, ruleset: dict) -> None:
        """A rule with no binding is an orphan by construction — making it
        uncreatable is cheaper than detecting it afterwards."""
        rel = _relationships(ruleset)["binding"]
        assert rel["peer"] == "InfrastructureBinding"
        assert rel["cardinality"] == "one"
        assert rel["optional"] is False

    def test_binding_pairs_with_the_binding_side(self) -> None:
        """Both ends must share an identifier or the graph only walks one way."""
        intent_schema = yaml.safe_load((SCHEMA_PATH.parent / "connectivity_intent.yml").read_text())
        binding = next(n for n in intent_schema["nodes"] if n["name"] == "Binding")
        reverse = {r["name"]: r for r in binding["relationships"]}["rule_sets"]
        forward = yaml.safe_load(SCHEMA_PATH.read_text())["nodes"][0]
        forward_rel = {r["name"]: r for r in forward["relationships"]}["binding"]
        assert reverse["identifier"] == forward_rel["identifier"]
        assert reverse["peer"] == "FirewallRuleSet"
