"""Unit tests for the operational intent schema (Issue #161).

Validates the 3-object operational override model from the intent-model
skill: OperationalOverride (the deviation), OverrideWindow (time bounds),
and OverrideAction (the config change applied). Overrides are always
time-bounded and auditable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SCHEMA_PATH = Path(__file__).parents[2] / "backend" / "network_synapse" / "schemas" / "operational_override.yml"


@pytest.fixture(scope="module")
def nodes_by_kind() -> dict[str, dict]:
    """Schema nodes keyed by their computed kind (namespace + name)."""
    schema = yaml.safe_load(SCHEMA_PATH.read_text())
    return {f"{n['namespace']}{n['name']}": n for n in schema.get("nodes", [])}


def _attributes(node: dict) -> dict[str, dict]:
    return {a["name"]: a for a in node.get("attributes", [])}


def _relationships(node: dict) -> dict[str, dict]:
    return {r["name"]: r for r in node.get("relationships", [])}


@pytest.mark.unit
class TestSchemaShape:
    """The three operational intent objects exist."""

    def test_all_three_kinds_defined(self, nodes_by_kind: dict) -> None:
        """OperationalOverride, OverrideWindow, and OverrideAction are all present."""
        missing = {"OperationalOverride", "OverrideWindow", "OverrideAction"} - set(nodes_by_kind)
        assert not missing, f"missing kinds: {sorted(missing)}"

    def test_schema_file_is_in_the_load_order(self) -> None:
        """The loader must ship the new schema after the device schemas."""
        from network_synapse.schemas.load_schemas import SCHEMA_LOAD_ORDER

        names = [Path(entry).name for entry in SCHEMA_LOAD_ORDER]
        assert "operational_override.yml" in names
        assert names.index("operational_override.yml") > names.index("network_device.yml")


@pytest.mark.unit
class TestOperationalOverride:
    """The override object itself."""

    def test_override_type_covers_the_four_operational_scenarios(self, nodes_by_kind: dict) -> None:
        """override_type is a dropdown with the four documented types."""
        attr = _attributes(nodes_by_kind["OperationalOverride"])["override_type"]
        assert attr["kind"] == "Dropdown"
        choices = {c["name"] for c in attr["choices"]}
        assert choices == {"admin_shutdown", "maintenance_mode", "traffic_drain", "emergency_bypass"}

    def test_status_tracks_the_override_lifecycle(self, nodes_by_kind: dict) -> None:
        """status covers pending through reverted/revert_failed/cancelled."""
        attr = _attributes(nodes_by_kind["OperationalOverride"])["status"]
        assert attr["kind"] == "Dropdown"
        choices = {c["name"] for c in attr["choices"]}
        assert {"pending", "active", "reverted", "revert_failed", "cancelled"} <= choices

    def test_override_records_reason_owner_and_origin(self, nodes_by_kind: dict) -> None:
        """Accountability metadata is mandatory for reason, present for owner/origin."""
        attrs = _attributes(nodes_by_kind["OperationalOverride"])
        assert attrs["reason"].get("optional") is not True, "reason must be required"
        assert "owner" in attrs
        assert "origin" in attrs

    def test_override_is_bound_to_a_device_window_and_actions(self, nodes_by_kind: dict) -> None:
        """Relationships: one device, one window, many actions."""
        rels = _relationships(nodes_by_kind["OperationalOverride"])
        assert rels["device"]["peer"] == "DcimDevice"
        assert rels["device"]["cardinality"] == "one"
        assert rels["window"]["peer"] == "OverrideWindow"
        assert rels["window"]["cardinality"] == "one"
        assert rels["actions"]["peer"] == "OverrideAction"
        assert rels["actions"]["cardinality"] == "many"


@pytest.mark.unit
class TestOverrideWindow:
    """Time bounds — overrides are always time-bounded."""

    def test_end_time_is_required(self, nodes_by_kind: dict) -> None:
        """An override without an end time is the anti-pattern the model forbids."""
        attrs = _attributes(nodes_by_kind["OverrideWindow"])
        assert attrs["end_time"]["kind"] == "DateTime"
        assert attrs["end_time"].get("optional") is not True

    def test_window_supports_auto_revert_and_extension_tracking(self, nodes_by_kind: dict) -> None:
        """auto_revert defaults on; extension_count starts at zero."""
        attrs = _attributes(nodes_by_kind["OverrideWindow"])
        assert attrs["auto_revert"]["kind"] == "Boolean"
        assert attrs["auto_revert"].get("default_value") is True
        assert attrs["extension_count"]["kind"] == "Number"
        assert attrs["extension_count"].get("default_value") == 0


@pytest.mark.unit
class TestOverrideAction:
    """The specific config change, with before/after state for audit."""

    def test_action_captures_original_and_override_state(self, nodes_by_kind: dict) -> None:
        """original_state (audit/manual fallback) and override_state are JSON blobs."""
        attrs = _attributes(nodes_by_kind["OverrideAction"])
        assert attrs["original_state"]["kind"] == "JSON"
        assert attrs["override_state"]["kind"] == "JSON"

    def test_action_names_its_target(self, nodes_by_kind: dict) -> None:
        """action_type and target_object identify what was changed."""
        attrs = _attributes(nodes_by_kind["OverrideAction"])
        assert "action_type" in attrs
        assert "target_object" in attrs
