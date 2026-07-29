"""Unit tests for the connectivity intent schemas (Issue #39).

Middle two objects of the business intent chain (intent-model skill):

    ApplicationService -> ServiceEndpoint -> ConnectivityIntent
      -> InfrastructureBinding -> FirewallRuleSet
                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^ this file

ConnectivityIntent is the join: a declared need for two endpoints to talk.
Its `status` is what makes the orphaned-rule check (#44) possible — a
FirewallRuleSet still deployed under a decommissioned intent is precisely
the audit violation the platform exists to surface.

InfrastructureBinding separates *what was asked for* from *how it was
realised*, so the same intent can be satisfied by a firewall rule today and
an ACL tomorrow without rewriting the business layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCHEMA_PATH = Path(__file__).parents[2] / "backend" / "network_synapse" / "schemas" / "connectivity_intent.yml"


@pytest.fixture(scope="module")
def nodes_by_kind() -> dict[str, dict]:
    assert SCHEMA_PATH.exists(), f"{SCHEMA_PATH} does not exist"
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    return {f"{n['namespace']}{n['name']}": n for n in schema.get("nodes", [])}


def _attributes(node: dict) -> dict[str, dict]:
    return {a["name"]: a for a in node.get("attributes", [])}


def _relationships(node: dict) -> dict[str, dict]:
    return {r["name"]: r for r in node.get("relationships", [])}


@pytest.mark.unit
class TestSchemaShape:
    def test_both_kinds_defined(self, nodes_by_kind: dict) -> None:
        missing = {"ConnectivityIntent", "InfrastructureBinding"} - set(nodes_by_kind)
        assert not missing, f"missing kinds: {sorted(missing)}"

    def test_loads_after_application_service(self) -> None:
        """It references ServiceEndpoint, which application_service.yml defines."""
        from network_synapse.schemas.load_schemas import SCHEMA_LOAD_ORDER

        names = [Path(entry).name for entry in SCHEMA_LOAD_ORDER]
        assert "connectivity_intent.yml" in names
        assert names.index("connectivity_intent.yml") > names.index("application_service.yml")

    @pytest.mark.parametrize("kind", ["ConnectivityIntent", "InfrastructureBinding"])
    def test_avoids_deprecated_schema_keys(self, nodes_by_kind: dict, kind: str) -> None:
        node = nodes_by_kind[kind]
        assert "display_labels" not in node
        assert "default_filter" not in node

    @pytest.mark.parametrize("kind", ["ConnectivityIntent", "InfrastructureBinding"])
    def test_declares_an_explicit_human_friendly_id(self, nodes_by_kind: dict, kind: str) -> None:
        """Seed data (#41) and lineage queries (#42) address objects by name.

        Relying on Infrahub inferring the HFID gave inconsistent lookups —
        creates resolved `hfid: ["name"]` but deletes could not find the same
        node. Declaring it explicitly, as the base library does, removes the
        ambiguity.
        """
        assert nodes_by_kind[kind].get("human_friendly_id") == ["name__value"]


@pytest.mark.unit
class TestConnectivityIntent:
    def test_status_covers_the_documented_lifecycle(self, nodes_by_kind: dict) -> None:
        attr = _attributes(nodes_by_kind["ConnectivityIntent"])["status"]
        assert attr["kind"] == "Dropdown"
        assert {c["name"] for c in attr["choices"]} == {
            "requested",
            "approved",
            "active",
            "decommissioned",
        }

    def test_new_intents_default_to_requested(self, nodes_by_kind: dict) -> None:
        """Nothing should become active without passing through approval."""
        attr = _attributes(nodes_by_kind["ConnectivityIntent"])["status"]
        assert attr["default_value"] == "requested"

    def test_justification_is_mandatory(self, nodes_by_kind: dict) -> None:
        """'Why does this connectivity exist' is the audit's second question."""
        attr = _attributes(nodes_by_kind["ConnectivityIntent"])["justification"]
        assert attr.get("optional") is not True

    def test_has_distinct_source_and_destination_endpoints(self, nodes_by_kind: dict) -> None:
        rels = _relationships(nodes_by_kind["ConnectivityIntent"])
        assert rels["source_endpoint"]["peer"] == "ServiceEndpoint"
        assert rels["destination_endpoint"]["peer"] == "ServiceEndpoint"

    def test_endpoint_relationships_use_separate_identifiers(self, nodes_by_kind: dict) -> None:
        """Two relationships to the same peer collapse into one without this.

        Sharing an identifier would make source and destination
        indistinguishable — the direction of the flow would be lost.
        """
        rels = _relationships(nodes_by_kind["ConnectivityIntent"])
        source = rels["source_endpoint"]["identifier"]
        destination = rels["destination_endpoint"]["identifier"]
        assert source
        assert destination
        assert source != destination

    def test_both_endpoints_are_required(self, nodes_by_kind: dict) -> None:
        rels = _relationships(nodes_by_kind["ConnectivityIntent"])
        assert rels["source_endpoint"]["optional"] is False
        assert rels["destination_endpoint"]["optional"] is False

    def test_endpoints_are_single_valued(self, nodes_by_kind: dict) -> None:
        rels = _relationships(nodes_by_kind["ConnectivityIntent"])
        assert rels["source_endpoint"]["cardinality"] == "one"
        assert rels["destination_endpoint"]["cardinality"] == "one"

    def test_records_when_it_was_decommissioned(self, nodes_by_kind: dict) -> None:
        """Feeds intent_decommission_age_days, declared in metrics.py but
        never emitted because nothing modelled the decommission date (#193)."""
        attr = _attributes(nodes_by_kind["ConnectivityIntent"])["decommissioned_at"]
        assert attr["kind"] == "DateTime"
        assert attr.get("optional") is True

    def test_has_many_bindings(self, nodes_by_kind: dict) -> None:
        """One intent may be realised on several devices."""
        rel = _relationships(nodes_by_kind["ConnectivityIntent"])["bindings"]
        assert rel["peer"] == "InfrastructureBinding"
        assert rel["cardinality"] == "many"


@pytest.mark.unit
class TestInfrastructureBinding:
    def test_binding_type_covers_the_documented_mechanisms(self, nodes_by_kind: dict) -> None:
        attr = _attributes(nodes_by_kind["InfrastructureBinding"])["binding_type"]
        assert attr["kind"] == "Dropdown"
        assert {c["name"] for c in attr["choices"]} == {
            "firewall_rule",
            "route_policy",
            "acl",
            "load_balancer",
        }

    def test_belongs_to_exactly_one_intent(self, nodes_by_kind: dict) -> None:
        """A binding with no intent is an orphan by construction — the thing
        the compliance check (#44) exists to find."""
        rel = _relationships(nodes_by_kind["InfrastructureBinding"])["intent"]
        assert rel["peer"] == "ConnectivityIntent"
        assert rel["cardinality"] == "one"
        assert rel["optional"] is False

    def test_intent_relationship_is_the_inverse_of_bindings(self, nodes_by_kind: dict) -> None:
        forward = _relationships(nodes_by_kind["ConnectivityIntent"])["bindings"]
        reverse = _relationships(nodes_by_kind["InfrastructureBinding"])["intent"]
        assert forward.get("identifier") == reverse.get("identifier")
        assert forward.get("identifier"), "relationship pair needs an explicit identifier"

    def test_binds_to_a_device(self, nodes_by_kind: dict) -> None:
        """Reverse audit starts from a device; without this the walk from a
        deployed rule back to its intent has no first hop."""
        rel = _relationships(nodes_by_kind["InfrastructureBinding"])["device"]
        assert rel["peer"] == "DcimDevice"
        assert rel["cardinality"] == "one"
