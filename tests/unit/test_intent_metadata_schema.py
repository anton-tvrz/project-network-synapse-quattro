"""Unit tests for intent metadata schema attributes (Issue #155).

Structured intent needs ownership, origin, and validity metadata (per the
intent-vs-operational-state analysis). Every extended SoT kind must carry:

- owner       (Text)     — team/person accountable for the intent
- origin      (Text)     — change ref / ticket that introduced it
- valid_until (DateTime) — validity period; groundwork for OperationalOverride (#63)

All three are optional so existing seed data keeps loading unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCHEMA_DIR = Path(__file__).parents[2] / "backend" / "network_synapse" / "schemas"

# Schema file -> extended kind that must carry the metadata attributes
EXTENDED_KINDS = {
    "network_device.yml": "DcimDevice",
    "network_interface.yml": "InterfacePhysical",
    "bgp_session.yml": "RoutingBGPSession",
}

METADATA_ATTRIBUTES = {
    "owner": "Text",
    "origin": "Text",
    "valid_until": "DateTime",
}


def _node_attributes(schema_file: str, kind: str) -> dict[str, dict]:
    """The attribute definitions of `kind` in `schema_file`, keyed by name."""
    schema = yaml.safe_load((SCHEMA_DIR / schema_file).read_text())
    for node in schema.get("extensions", {}).get("nodes", []):
        if node.get("kind") == kind:
            return {a["name"]: a for a in node.get("attributes", [])}
    pytest.fail(f"{schema_file}: no extension node for kind {kind!r}")


@pytest.mark.unit
class TestIntentMetadataAttributes:
    """Every extended SoT kind carries owner/origin/valid_until."""

    @pytest.mark.parametrize(("schema_file", "kind"), sorted(EXTENDED_KINDS.items()))
    def test_kind_has_all_metadata_attributes(self, schema_file: str, kind: str) -> None:
        """owner, origin, and valid_until exist on the extended kind."""
        attributes = _node_attributes(schema_file, kind)
        missing = set(METADATA_ATTRIBUTES) - set(attributes)
        assert not missing, f"{kind} missing metadata attributes: {sorted(missing)}"

    @pytest.mark.parametrize(("schema_file", "kind"), sorted(EXTENDED_KINDS.items()))
    def test_metadata_attributes_have_correct_kinds(self, schema_file: str, kind: str) -> None:
        """valid_until is a DateTime; owner and origin are Text."""
        attributes = _node_attributes(schema_file, kind)
        for name, expected_kind in METADATA_ATTRIBUTES.items():
            assert attributes[name]["kind"] == expected_kind, f"{kind}.{name}"

    @pytest.mark.parametrize(("schema_file", "kind"), sorted(EXTENDED_KINDS.items()))
    def test_metadata_attributes_are_optional(self, schema_file: str, kind: str) -> None:
        """Metadata must be optional so existing seed data loads unchanged."""
        attributes = _node_attributes(schema_file, kind)
        for name in METADATA_ATTRIBUTES:
            assert attributes[name].get("optional") is True, f"{kind}.{name} must be optional"

    @pytest.mark.parametrize(("schema_file", "kind"), sorted(EXTENDED_KINDS.items()))
    def test_metadata_attributes_have_descriptions(self, schema_file: str, kind: str) -> None:
        """Each metadata attribute documents what it records."""
        attributes = _node_attributes(schema_file, kind)
        for name in METADATA_ATTRIBUTES:
            assert attributes[name].get("description"), f"{kind}.{name} missing description"

    def test_every_metadata_schema_file_is_in_the_load_order(self) -> None:
        """The loader must ship every schema file that now carries extensions."""
        from network_synapse.schemas.load_schemas import SCHEMA_LOAD_ORDER

        loaded = {Path(entry).name for entry in SCHEMA_LOAD_ORDER}
        missing = set(EXTENDED_KINDS) - loaded
        assert not missing, f"schema files not in SCHEMA_LOAD_ORDER: {sorted(missing)}"
