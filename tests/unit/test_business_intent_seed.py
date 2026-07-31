"""Unit tests for the business intent seed data (Issue #41).

Seeds an example trading-application connectivity chain so the lineage the
schemas (#38, #39, #40) make possible has something to demonstrate:

    trading-gateway -> gw-fix-out -> gw-to-market-data -> leaf02 binding
      -> permit rule

The seed deliberately includes a *second*, decommissioned chain whose rule is
still deployed. That is the compliance violation the platform exists to
surface, and without seeded data for it the orphan check (#44) and the
Compliance dashboard have nothing to show in a demo.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from network_synapse.data import populate_sot

SEED_PATH = Path(__file__).parents[2] / "backend" / "network_synapse" / "data" / "business_intent.yml"
BASE_URL = "http://infrahub.test:8000"


@pytest.fixture(scope="module")
def seed() -> dict:
    assert SEED_PATH.exists(), f"{SEED_PATH} does not exist"
    return yaml.safe_load(SEED_PATH.read_text())


# ---------------------------------------------------------------------------
# Seed file shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSeedShape:
    def test_defines_all_five_chain_sections(self, seed: dict) -> None:
        expected = {
            "application_services",
            "service_endpoints",
            "connectivity_intents",
            "infrastructure_bindings",
            "firewall_rule_sets",
        }
        assert expected <= set(seed)

    def test_every_endpoint_references_a_defined_service(self, seed: dict) -> None:
        services = {s["name"] for s in seed["application_services"]}
        for endpoint in seed["service_endpoints"]:
            assert endpoint["service"] in services, f"{endpoint['name']} -> unknown service"

    def test_every_intent_references_defined_endpoints(self, seed: dict) -> None:
        endpoints = {e["name"] for e in seed["service_endpoints"]}
        for intent in seed["connectivity_intents"]:
            assert intent["source_endpoint"] in endpoints
            assert intent["destination_endpoint"] in endpoints

    def test_every_binding_references_a_defined_intent(self, seed: dict) -> None:
        intents = {i["name"] for i in seed["connectivity_intents"]}
        for binding in seed["infrastructure_bindings"]:
            assert binding["intent"] in intents

    def test_every_rule_references_a_defined_binding(self, seed: dict) -> None:
        bindings = {b["name"] for b in seed["infrastructure_bindings"]}
        for rule in seed["firewall_rule_sets"]:
            assert rule["binding"] in bindings

    def test_bindings_target_devices_the_device_seed_creates(self, seed: dict) -> None:
        """A binding pointing at an unseeded device fails at load time.

        Only spine01/leaf01/leaf02 are in seed_data.yml — the firewall node
        is not yet modelled in the SoT (#186).
        """
        device_seed = yaml.safe_load((SEED_PATH.parent / "seed_data.yml").read_text())
        known = {d["name"] for d in device_seed["devices"]}
        for binding in seed["infrastructure_bindings"]:
            assert binding["device"] in known, f"{binding['name']} -> unseeded device {binding['device']}"


# ---------------------------------------------------------------------------
# The demonstrable scenarios
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDemoScenarios:
    def test_has_a_complete_active_chain(self, seed: dict) -> None:
        """The 'every rule traces to an owner' beat needs one clean path."""
        active = [i for i in seed["connectivity_intents"] if i["status"] == "active"]
        assert active, "no active intent to demonstrate forward lineage"

    def test_has_a_decommissioned_intent_with_a_surviving_rule(self, seed: dict) -> None:
        """The compliance beat: an orphan, seeded so it can be shown."""
        retired = {i["name"] for i in seed["connectivity_intents"] if i["status"] == "decommissioned"}
        assert retired, "no decommissioned intent — orphan detection has nothing to find"

        orphan_bindings = {b["name"] for b in seed["infrastructure_bindings"] if b["intent"] in retired}
        orphan_rules = [r for r in seed["firewall_rule_sets"] if r["binding"] in orphan_bindings]
        assert orphan_rules, "decommissioned intent has no surviving rule — not an orphan"

    def test_decommissioned_intent_records_when(self, seed: dict) -> None:
        """intent_decommission_age_days needs a date to measure from."""
        for intent in seed["connectivity_intents"]:
            if intent["status"] == "decommissioned":
                assert intent.get("decommissioned_at")

    def test_every_service_names_an_owner(self, seed: dict) -> None:
        """An ownerless service breaks the audit the seed exists to show."""
        for service in seed["application_services"]:
            assert service.get("owner")

    def test_rules_use_valid_cidr_prefixes(self, seed: dict) -> None:
        """IPNetwork rejects bad prefixes on write — fail here instead."""
        import ipaddress

        for rule in seed["firewall_rule_sets"]:
            ipaddress.ip_network(rule["source_network"])
            ipaddress.ip_network(rule["destination_network"])


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPopulateBusinessIntent:
    def test_creates_objects_in_dependency_order(self) -> None:
        """A binding cannot be created before the intent it references."""
        created: list[str] = []

        def fake_get_or_create(client, base_url, type_name, *args, **kwargs):
            created.append(type_name)
            return f"id-{type_name}-{len(created)}"

        seed = yaml.safe_load(SEED_PATH.read_text())
        with patch.object(populate_sot, "get_or_create", side_effect=fake_get_or_create):
            populate_sot.populate_business_intent(Mock(), BASE_URL, seed, {"leaf01": "d1", "leaf02": "d2"})

        first = {}
        for index, kind in enumerate(created):
            first.setdefault(kind, index)
        order = [
            "ApplicationService",
            "ServiceEndpoint",
            "ConnectivityIntent",
            "InfrastructureBinding",
            "FirewallRuleSet",
        ]
        positions = [first[kind] for kind in order if kind in first]
        assert positions == sorted(positions), f"created out of order: {created}"

    def test_is_a_noop_when_the_seed_has_no_business_intent(self) -> None:
        """seed_data.yml has no business intent section; must not explode."""
        with patch.object(populate_sot, "get_or_create") as mock:
            populate_sot.populate_business_intent(Mock(), BASE_URL, {}, {})
        mock.assert_not_called()

    def test_skips_bindings_for_unknown_devices(self) -> None:
        """Rather than fail the whole seed on one unmodelled device."""
        seed = {
            "application_services": [],
            "service_endpoints": [],
            "connectivity_intents": [],
            "infrastructure_bindings": [{"name": "b", "intent": "i", "device": "nonexistent", "binding_type": "acl"}],
            "firewall_rule_sets": [],
        }
        with patch.object(populate_sot, "get_or_create") as mock:
            populate_sot.populate_business_intent(Mock(), BASE_URL, seed, {"leaf01": "d1"})
        assert not any(call.args[2] == "InfrastructureBinding" for call in mock.call_args_list)
