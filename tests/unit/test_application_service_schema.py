"""Unit tests for the business intent root schemas (Issue #38).

First two objects of the 5-object business intent chain (intent-model skill):

    ApplicationService -> ServiceEndpoint -> ConnectivityIntent
      -> InfrastructureBinding -> FirewallRuleSet

ApplicationService is the root of every lineage query. The reverse-audit path
("which business owner asked for this firewall rule?") terminates here, so
the owner attribute is mandatory — an ApplicationService without one would
produce a lineage chain that answers every question except the one the audit
asks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCHEMA_PATH = Path(__file__).parents[2] / "backend" / "network_synapse" / "schemas" / "application_service.yml"


@pytest.fixture(scope="module")
def nodes_by_kind() -> dict[str, dict]:
    """Schema nodes keyed by their computed kind (namespace + name)."""
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
        missing = {"ApplicationService", "ServiceEndpoint"} - set(nodes_by_kind)
        assert not missing, f"missing kinds: {sorted(missing)}"

    def test_schema_file_is_in_the_load_order(self) -> None:
        from network_synapse.schemas.load_schemas import SCHEMA_LOAD_ORDER

        names = [Path(entry).name for entry in SCHEMA_LOAD_ORDER]
        assert "application_service.yml" in names

    def test_loads_after_the_base_schemas(self) -> None:
        """It references no base kinds yet, but must sit in the project batch."""
        from network_synapse.schemas.load_schemas import SCHEMA_LOAD_BATCHES

        project_batch = [Path(entry).name for entry in SCHEMA_LOAD_BATCHES[-1]]
        assert "application_service.yml" in project_batch


@pytest.mark.unit
class TestNoDeprecatedSchemaKeys:
    """Infrahub warns on `display_labels` and `default_filter` at load time.

    The pre-existing schemas still use them (tracked separately); new ones
    should not add to the pile. Scoped to this file deliberately — widening
    it to every schema would fail on the known offenders.
    """

    @pytest.mark.parametrize("kind", ["ApplicationService", "ServiceEndpoint"])
    def test_uses_display_label_not_display_labels(self, nodes_by_kind: dict, kind: str) -> None:
        node = nodes_by_kind[kind]
        assert "display_labels" not in node
        assert node.get("display_label")

    @pytest.mark.parametrize("kind", ["ApplicationService", "ServiceEndpoint"])
    def test_does_not_use_default_filter(self, nodes_by_kind: dict, kind: str) -> None:
        assert "default_filter" not in nodes_by_kind[kind]

    @pytest.mark.parametrize("kind", ["ApplicationService", "ServiceEndpoint"])
    def test_declares_an_explicit_human_friendly_id(self, nodes_by_kind: dict, kind: str) -> None:
        """Seed data (#41) and lineage queries (#42) address objects by name."""
        assert nodes_by_kind[kind].get("human_friendly_id") == ["name__value"]


@pytest.mark.unit
class TestApplicationService:
    def test_name_is_unique(self, nodes_by_kind: dict) -> None:
        """Seed data and lineage queries look services up by name."""
        attr = _attributes(nodes_by_kind["ApplicationService"])["name"]
        assert attr["kind"] == "Text"
        assert attr.get("unique") is True

    def test_owner_is_mandatory(self, nodes_by_kind: dict) -> None:
        """The reverse-audit path terminates at the owner; it cannot be absent."""
        attr = _attributes(nodes_by_kind["ApplicationService"])["owner"]
        assert attr["kind"] == "Text"
        assert attr.get("optional") is not True

    def test_criticality_covers_p1_to_p4(self, nodes_by_kind: dict) -> None:
        attr = _attributes(nodes_by_kind["ApplicationService"])["criticality"]
        assert attr["kind"] == "Dropdown"
        assert {c["name"] for c in attr["choices"]} == {"P1", "P2", "P3", "P4"}

    def test_environment_is_constrained(self, nodes_by_kind: dict) -> None:
        """Free text here would make 'all production services' unanswerable."""
        attr = _attributes(nodes_by_kind["ApplicationService"])["environment"]
        assert attr["kind"] == "Dropdown"
        assert {"production", "development"} <= {c["name"] for c in attr["choices"]}

    def test_has_many_endpoints(self, nodes_by_kind: dict) -> None:
        rel = _relationships(nodes_by_kind["ApplicationService"])["endpoints"]
        assert rel["peer"] == "ServiceEndpoint"
        assert rel["cardinality"] == "many"

    def test_endpoints_are_components_of_the_service(self, nodes_by_kind: dict) -> None:
        """Component, so endpoints are owned by the service, not shared."""
        rel = _relationships(nodes_by_kind["ApplicationService"])["endpoints"]
        assert rel["kind"] == "Component"

    def test_carries_intent_origin_metadata(self, nodes_by_kind: dict) -> None:
        """Consistent with the #155 intent metadata on the SoT kinds."""
        assert "origin" in _attributes(nodes_by_kind["ApplicationService"])


@pytest.mark.unit
class TestServiceEndpoint:
    def test_protocol_is_constrained(self, nodes_by_kind: dict) -> None:
        attr = _attributes(nodes_by_kind["ServiceEndpoint"])["protocol"]
        assert attr["kind"] == "Dropdown"
        assert {"tcp", "udp", "icmp"} <= {c["name"] for c in attr["choices"]}

    def test_port_is_numeric(self, nodes_by_kind: dict) -> None:
        """Rendering a firewall rule does arithmetic-free comparison on this."""
        attr = _attributes(nodes_by_kind["ServiceEndpoint"])["port"]
        assert attr["kind"] == "Number"

    def test_port_is_optional_for_icmp(self, nodes_by_kind: dict) -> None:
        """ICMP has no port; a mandatory port would make ICMP unmodellable."""
        attr = _attributes(nodes_by_kind["ServiceEndpoint"])["port"]
        assert attr.get("optional") is True

    def test_direction_is_constrained(self, nodes_by_kind: dict) -> None:
        attr = _attributes(nodes_by_kind["ServiceEndpoint"])["direction"]
        assert attr["kind"] == "Dropdown"
        assert {"inbound", "outbound"} <= {c["name"] for c in attr["choices"]}

    def test_belongs_to_exactly_one_service(self, nodes_by_kind: dict) -> None:
        """The forward lineage walk depends on this being single-valued."""
        rel = _relationships(nodes_by_kind["ServiceEndpoint"])["service"]
        assert rel["peer"] == "ApplicationService"
        assert rel["cardinality"] == "one"
        assert rel.get("optional") is False

    def test_service_relationship_is_the_inverse_of_endpoints(self, nodes_by_kind: dict) -> None:
        """Both sides must name the same identifier or the graph is one-way."""
        forward = _relationships(nodes_by_kind["ApplicationService"])["endpoints"]
        reverse = _relationships(nodes_by_kind["ServiceEndpoint"])["service"]
        assert forward.get("identifier") == reverse.get("identifier")
        assert forward.get("identifier"), "relationship pair needs an explicit identifier"
