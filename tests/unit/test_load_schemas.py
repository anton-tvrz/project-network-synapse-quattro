"""Unit tests for the Infrahub schema loading script.

Covers YAML parsing, the single-schema load paths (success, warnings,
validation error, connection error), schema verification, and the
--dry-run flow against the real schema files in the repo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import Mock

import httpx
import pytest

from network_synapse.schemas import load_schemas

if TYPE_CHECKING:
    from pathlib import Path

BASE_URL = "http://infrahub.test:8000"

VALID_SCHEMA = {"nodes": [{"name": "Device", "namespace": "Dcim"}]}


def _response(status_code: int = 200, json_body: dict | None = None, text: str = "") -> Mock:
    resp = Mock(status_code=status_code, text=text)
    if json_body is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = json_body
    return resp


# ---------------------------------------------------------------------------
# YAML / path helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHelpers:
    def test_get_project_root_finds_git_root(self) -> None:
        root = load_schemas.get_project_root()
        assert (root / ".git").exists()

    def test_load_yaml_file_parses_content(self, tmp_path: Path) -> None:
        f = tmp_path / "schema.yml"
        f.write_text("nodes:\n  - name: Device\n")
        assert load_schemas.load_yaml_file(f) == {"nodes": [{"name": "Device"}]}

    def test_load_yaml_file_empty_returns_empty_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.yml"
        f.write_text("")
        assert load_schemas.load_yaml_file(f) == {}

    def test_schema_load_order_flattens_batches(self) -> None:
        flattened = [f for batch in load_schemas.SCHEMA_LOAD_BATCHES for f in batch]
        assert flattened == load_schemas.SCHEMA_LOAD_ORDER

    def test_all_schema_files_exist_in_repo(self) -> None:
        """The hardcoded batch paths must point at real files."""
        root = load_schemas.get_project_root()
        missing = [p for p in load_schemas.SCHEMA_LOAD_ORDER if not (root / p).exists()]
        assert missing == []


# ---------------------------------------------------------------------------
# load_schema_into_infrahub
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadSchemaIntoInfrahub:
    def test_success_returns_true(self) -> None:
        client = Mock()
        client.post.return_value = _response(200, {})

        assert load_schemas.load_schema_into_infrahub(client, BASE_URL, VALID_SCHEMA, "dcim") is True
        args, kwargs = client.post.call_args
        assert args[0] == f"{BASE_URL}/api/schema/load"
        assert kwargs["json"] == {"schemas": [VALID_SCHEMA]}

    def test_success_with_warnings_returns_true(self) -> None:
        client = Mock()
        client.post.return_value = _response(200, {"errors": [{"message": "deprecated attr"}]})

        assert load_schemas.load_schema_into_infrahub(client, BASE_URL, VALID_SCHEMA, "dcim") is True

    def test_empty_schema_is_skipped_without_api_call(self) -> None:
        client = Mock()

        assert load_schemas.load_schema_into_infrahub(client, BASE_URL, {"version": "1.0"}, "doc-only") is True
        client.post.assert_not_called()

    def test_validation_error_422_returns_false(self) -> None:
        client = Mock()
        client.post.return_value = _response(422, {"detail": "bad schema"})

        assert load_schemas.load_schema_into_infrahub(client, BASE_URL, VALID_SCHEMA, "dcim") is False

    def test_other_http_error_returns_false(self) -> None:
        client = Mock()
        client.post.return_value = _response(500, {}, text="internal error")

        assert load_schemas.load_schema_into_infrahub(client, BASE_URL, VALID_SCHEMA, "dcim") is False

    def test_connection_error_returns_false(self) -> None:
        client = Mock()
        client.post.side_effect = httpx.ConnectError("refused")

        assert load_schemas.load_schema_into_infrahub(client, BASE_URL, VALID_SCHEMA, "dcim") is False


# ---------------------------------------------------------------------------
# verify_schema_loaded
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifySchemaLoaded:
    def test_reports_present_nodes(self, capsys: pytest.CaptureFixture) -> None:
        client = Mock()
        client.get.return_value = _response(
            200,
            {
                "nodes": {
                    "IpamVRF": {},
                    "RoutingAutonomousSystem": {},
                    "RoutingBGPPeerGroup": {},
                    "RoutingBGPSession": {},
                    "DcimDevice": {},
                    "InterfacePhysical": {},
                },
                "generics": {"RoutingProtocol": {}},
            },
        )

        load_schemas.verify_schema_loaded(client, BASE_URL)

        out = capsys.readouterr().out
        assert "All expected BGP/Routing nodes present" in out

    def test_reports_missing_nodes(self, capsys: pytest.CaptureFixture) -> None:
        client = Mock()
        client.get.return_value = _response(200, {"nodes": {"DcimDevice": {}}, "generics": {}})

        load_schemas.verify_schema_loaded(client, BASE_URL)

        out = capsys.readouterr().out
        assert "Missing expected nodes" in out
        assert "IpamVRF" in out

    def test_swallows_exceptions(self, capsys: pytest.CaptureFixture) -> None:
        client = Mock()
        client.get.side_effect = httpx.ConnectError("refused")

        load_schemas.verify_schema_loaded(client, BASE_URL)  # must not raise

        assert "Could not verify schemas" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main --dry-run
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMainDryRun:
    def test_dry_run_parses_all_repo_schemas(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr("sys.argv", ["load_schemas.py", "--dry-run"])

        load_schemas.main()

        out = capsys.readouterr().out
        assert "Dry run complete" in out
        assert out.count("📄 Parsed:") == len(load_schemas.SCHEMA_LOAD_ORDER)

    def test_missing_schema_file_exits_nonzero(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr("sys.argv", ["load_schemas.py", "--dry-run"])
        monkeypatch.setattr(load_schemas, "get_project_root", lambda: tmp_path)

        with pytest.raises(SystemExit) as exc_info:
            load_schemas.main()

        assert exc_info.value.code == 1
