"""Unit tests for InfrahubConfigClient lifecycle and query plumbing (Issue #141).

Tests cover:
  - URL/token resolution from arguments and environment
  - Header construction with and without API token
  - Lazy httpx client creation and auto-login flow
  - close() and context manager lifecycle
  - _graphql payload construction and GraphQL error handling
  - get_device_config router-id derivation from loopback interfaces
  - update_device_status validation and mutation paths
  - execute_transform success and failure paths

Query-method response parsing (get_device, get_device_interfaces,
get_device_bgp_sessions) is covered in test_config_generation.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from network_synapse.infrahub.client import (
    DeviceNotFoundError,
    InfrahubConfigClient,
)
from network_synapse.infrahub.models import DeviceData, InterfaceData

# ---------------------------------------------------------------------------
# Construction and header building
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClientConstruction:
    """Test URL/token resolution and header construction."""

    def test_url_trailing_slash_stripped(self):
        client = InfrahubConfigClient(url="http://test:8000/", token="tok")
        assert client.url == "http://test:8000"

    def test_url_defaults_from_env(self, monkeypatch):
        monkeypatch.setenv("INFRAHUB_URL", "http://from-env:8000")
        client = InfrahubConfigClient(token="tok")
        assert client.url == "http://from-env:8000"

    def test_url_falls_back_to_localhost(self, monkeypatch):
        monkeypatch.delenv("INFRAHUB_URL", raising=False)
        client = InfrahubConfigClient(token="tok")
        assert client.url == "http://localhost:8000"

    def test_token_defaults_from_env(self, monkeypatch):
        monkeypatch.setenv("INFRAHUB_TOKEN", "env-token")
        client = InfrahubConfigClient(url="http://test:8000")
        assert client.token == "env-token"  # noqa: S105

    def test_headers_with_token(self):
        client = InfrahubConfigClient(url="http://test:8000", token="my-key")
        headers = client._get_headers()
        assert headers["X-INFRAHUB-KEY"] == "my-key"
        assert headers["Content-Type"] == "application/json"

    def test_headers_without_token(self, monkeypatch):
        monkeypatch.delenv("INFRAHUB_TOKEN", raising=False)
        client = InfrahubConfigClient(url="http://test:8000")
        headers = client._get_headers()
        assert "X-INFRAHUB-KEY" not in headers


# ---------------------------------------------------------------------------
# Lazy client creation and auto-login
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClientLifecycle:
    """Test lazy httpx client creation, auto-login, and close/context manager."""

    def test_ensure_client_with_token_skips_login(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with (
            patch("network_synapse.infrahub.client.httpx.Client") as mock_httpx_cls,
            patch.object(client, "_auto_login") as mock_login,
        ):
            http = client._ensure_client()
        assert http is mock_httpx_cls.return_value
        mock_login.assert_not_called()

    def test_ensure_client_without_token_auto_logins_once(self, monkeypatch):
        monkeypatch.delenv("INFRAHUB_TOKEN", raising=False)
        client = InfrahubConfigClient(url="http://test:8000")
        with (
            patch("network_synapse.infrahub.client.httpx.Client"),
            patch.object(client, "_auto_login") as mock_login,
        ):
            first = client._ensure_client()
            second = client._ensure_client()
        assert first is second
        mock_login.assert_called_once()

    def test_auto_login_sets_bearer_header(self, monkeypatch):
        monkeypatch.delenv("INFRAHUB_TOKEN", raising=False)
        client = InfrahubConfigClient(url="http://test:8000")
        mock_http = MagicMock()
        mock_http.headers = {}
        mock_http.post.return_value.json.return_value = {"access_token": "abc123"}
        client._client = mock_http

        client._auto_login()

        assert mock_http.headers["Authorization"] == "Bearer abc123"
        assert client._authenticated is True
        mock_http.post.assert_called_once_with(
            "http://test:8000/api/auth/login",
            json={"username": "admin", "password": "infrahub"},  # pragma: allowlist secret
            timeout=10.0,
        )

    def test_auto_login_without_access_token_stays_unauthenticated(self, monkeypatch):
        monkeypatch.delenv("INFRAHUB_TOKEN", raising=False)
        client = InfrahubConfigClient(url="http://test:8000")
        mock_http = MagicMock()
        mock_http.headers = {}
        mock_http.post.return_value.json.return_value = {"detail": "unauthorized"}
        client._client = mock_http

        client._auto_login()

        assert "Authorization" not in mock_http.headers
        assert client._authenticated is False

    def test_auto_login_swallows_http_errors(self, monkeypatch):
        monkeypatch.delenv("INFRAHUB_TOKEN", raising=False)
        client = InfrahubConfigClient(url="http://test:8000")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.ConnectError("no route")
        client._client = mock_http

        client._auto_login()  # must not raise

        assert client._authenticated is False

    def test_auto_login_noop_without_client(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        client._auto_login()  # _client is None — must not raise
        assert client._client is None

    def test_close_closes_and_resets_client(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        mock_http = MagicMock()
        client._client = mock_http

        client.close()

        mock_http.close.assert_called_once()
        assert client._client is None

    def test_close_without_client_is_safe(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        client.close()  # must not raise
        assert client._client is None

    def test_context_manager_closes_on_exit(self):
        mock_http = MagicMock()
        with InfrahubConfigClient(url="http://test:8000", token="tok") as client:
            client._client = mock_http
        mock_http.close.assert_called_once()
        assert client._client is None


# ---------------------------------------------------------------------------
# GraphQL execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGraphQLExecution:
    """Test _graphql payload construction and error handling."""

    def _client_with_response(self, response: dict) -> tuple[InfrahubConfigClient, MagicMock]:
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        mock_http = MagicMock()
        mock_http.post.return_value.json.return_value = response
        client._client = mock_http
        return client, mock_http

    def test_graphql_posts_query_with_variables(self):
        client, mock_http = self._client_with_response({"data": {"ok": True}})

        result = client._graphql("query Q { x }", variables={"hostname": "spine01"})

        assert result == {"ok": True}
        mock_http.post.assert_called_once_with(
            "http://test:8000/graphql",
            json={"query": "query Q { x }", "variables": {"hostname": "spine01"}},
            timeout=30.0,
        )

    def test_graphql_omits_variables_key_when_none(self):
        client, mock_http = self._client_with_response({"data": {}})

        client._graphql("query Q { x }")

        payload = mock_http.post.call_args.kwargs["json"]
        assert "variables" not in payload

    def test_graphql_errors_raise_runtime_error(self):
        client, _ = self._client_with_response({"errors": [{"message": "field not found"}, {"message": "bad filter"}]})

        with pytest.raises(RuntimeError, match="field not found; bad filter"):
            client._graphql("query Q { x }")

    def test_graphql_missing_data_returns_empty_dict(self):
        client, _ = self._client_with_response({})
        assert client._graphql("query Q { x }") == {}

    def test_list_devices_aliases_get_all_device_hostnames(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with patch.object(client, "get_all_device_hostnames", return_value=["spine01"]) as mock_get:
            assert client.list_devices() == ["spine01"]
        mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# get_device_config — router-id derivation
# ---------------------------------------------------------------------------


def _make_device(**overrides) -> DeviceData:
    defaults = {"id": "device-id", "name": "spine01", "asn": 65000}
    return DeviceData(**{**defaults, **overrides})


@pytest.mark.unit
class TestGetDeviceConfig:
    """Test the aggregated device config fetch and router-id derivation."""

    def _patched_client(self, interfaces: list[InterfaceData]) -> InfrahubConfigClient:
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        client.get_device = MagicMock(return_value=_make_device())  # type: ignore[method-assign]
        client.get_device_interfaces = MagicMock(return_value=interfaces)  # type: ignore[method-assign]
        client.get_device_bgp_sessions = MagicMock(return_value=[])  # type: ignore[method-assign]
        return client

    def test_router_id_derived_from_loopback(self):
        client = self._patched_client(
            [
                InterfaceData(name="ethernet-1/1", role="fabric", ip_address="10.0.0.0/31"),
                InterfaceData(name="loopback0", role="loopback", ip_address="10.1.0.1/32"),
            ]
        )

        config = client.get_device_config("spine01")

        assert config.device.router_id == "10.1.0.1"
        assert len(config.interfaces) == 2
        assert config.bgp_sessions == []

    def test_loopback_without_ip_is_skipped(self):
        client = self._patched_client(
            [
                InterfaceData(name="loopback1", role="loopback", ip_address=None),
                InterfaceData(name="loopback0", role="loopback", ip_address="10.1.0.1/32"),
            ]
        )

        config = client.get_device_config("spine01")

        assert config.device.router_id == "10.1.0.1"

    def test_no_loopback_raises_value_error(self):
        client = self._patched_client([InterfaceData(name="ethernet-1/1", role="fabric", ip_address="10.0.0.0/31")])

        with pytest.raises(ValueError, match="cannot derive router_id"):
            client.get_device_config("spine01")


# ---------------------------------------------------------------------------
# update_device_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateDeviceStatus:
    """Test the device status update mutation."""

    def test_invalid_status_raises_value_error(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with pytest.raises(ValueError, match="Invalid device status 'bogus'"):
            client.update_device_status("spine01", "bogus")

    def test_successful_update_returns_pre_update_device(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        device = _make_device(status="active")
        mutation_response = {"DcimDeviceUpdate": {"ok": True, "object": {"id": "device-id"}}}
        with (
            patch.object(client, "get_device", return_value=device),
            patch.object(client, "_graphql", return_value=mutation_response) as mock_gql,
        ):
            result = client.update_device_status("spine01", "maintenance")

        assert result is device
        assert result.status == "active"  # pre-update snapshot
        mock_gql.assert_called_once()
        variables = mock_gql.call_args.kwargs["variables"]
        assert variables == {"data": {"id": "device-id", "status": {"value": "maintenance"}}}

    def test_failed_mutation_raises_runtime_error(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with (
            patch.object(client, "get_device", return_value=_make_device()),
            patch.object(client, "_graphql", return_value={"DcimDeviceUpdate": {"ok": False}}),
            pytest.raises(RuntimeError, match="Failed to update status"),
        ):
            client.update_device_status("spine01", "drained")

    def test_unknown_device_propagates_not_found(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with (
            patch.object(client, "get_device", side_effect=DeviceNotFoundError("ghost01")),
            pytest.raises(DeviceNotFoundError),
        ):
            client.update_device_status("ghost01", "active")


# ---------------------------------------------------------------------------
# update_override_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateOverrideStatus:
    """Test the OperationalOverride status update mutation (Issue #48)."""

    def _override_lookup(self, override_id: str = "override-id", status: str = "active") -> dict:
        return {"OperationalOverride": {"edges": [{"node": {"id": override_id, "status": {"value": status}}}]}}

    def test_invalid_status_raises_value_error(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with pytest.raises(ValueError, match="Invalid override status 'bogus'"):
            client.update_override_status("leaf01-drain", "bogus")

    def test_successful_update_returns_previous_status(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        responses = [
            self._override_lookup(status="active"),
            {"OperationalOverrideUpdate": {"ok": True}},
        ]
        with patch.object(client, "_graphql", side_effect=responses) as mock_gql:
            previous = client.update_override_status("leaf01-drain", "reverted")

        assert previous == "active"
        assert mock_gql.call_count == 2
        variables = mock_gql.call_args.kwargs["variables"]
        assert variables == {"data": {"id": "override-id", "status": {"value": "reverted"}}}

    def test_unknown_override_raises_runtime_error(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with (
            patch.object(client, "_graphql", return_value={"OperationalOverride": {"edges": []}}),
            pytest.raises(RuntimeError, match="Override 'ghost-drain' not found"),
        ):
            client.update_override_status("ghost-drain", "reverted")

    def test_failed_mutation_raises_runtime_error(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        responses = [
            self._override_lookup(),
            {"OperationalOverrideUpdate": {"ok": False}},
        ]
        with (
            patch.object(client, "_graphql", side_effect=responses),
            pytest.raises(RuntimeError, match="Failed to update status for override"),
        ):
            client.update_override_status("leaf01-drain", "cancelled")


# ---------------------------------------------------------------------------
# execute_transform
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteTransform:
    """Test server-side transform execution."""

    def test_returns_transform_data_as_string(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        response = {"InfrahubTransformPython": {"data": {"interface": []}}}
        with patch.object(client, "_graphql", return_value=response) as mock_gql:
            result = client.execute_transform("srlinux_interface_config", {"hostname": "spine01"})

        assert result == str({"interface": []})
        variables = mock_gql.call_args.kwargs["variables"]
        assert variables == {"name": "srlinux_interface_config", "params": {"hostname": "spine01"}}

    def test_omits_params_when_no_variables(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        response = {"InfrahubTransformPython": {"data": "{}"}}
        with patch.object(client, "_graphql", return_value=response) as mock_gql:
            client.execute_transform("srlinux_bgp_config")

        assert "params" not in mock_gql.call_args.kwargs["variables"]

    def test_missing_data_raises_runtime_error(self):
        client = InfrahubConfigClient(url="http://test:8000", token="tok")
        with (
            patch.object(client, "_graphql", return_value={"InfrahubTransformPython": {}}),
            pytest.raises(RuntimeError, match="returned no data"),
        ):
            client.execute_transform("srlinux_bgp_config")
