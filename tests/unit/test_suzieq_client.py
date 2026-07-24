"""Unit tests for the SuzieQ REST client (Issue #74).

The client is the shared backend entry point to the SuzieQ REST API served
by the collector stack (Issue #169). It fetches assert-table output over
HTTP so higher layers (drift scoring, override-aware validation) never talk
to SuzieQ directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from network_synapse.collector import suzieq_client as sc
from network_synapse.collector.suzieq_client import SuzieqClient


class TestAssertTable:
    def test_gets_assert_endpoint_with_token_and_namespace(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = [{"hostname": "spine01", "assert": "pass"}]
        with (
            patch.object(sc.httpx.Client, "get", return_value=response) as mock_get,
            SuzieqClient(url="http://suzieq:8530", token="tok", namespace="ns") as client,
        ):
            rows = client.assert_table("bgp")

        assert rows == [{"hostname": "spine01", "assert": "pass"}]
        called_url = mock_get.call_args.args[0]
        assert called_url == "http://suzieq:8530/api/v2/bgp/assert"
        params = mock_get.call_args.kwargs["params"]
        assert params["access_token"] == "tok"
        assert params["namespace"] == "ns"

    def test_trailing_slash_in_url_is_normalized(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = []
        with (
            patch.object(sc.httpx.Client, "get", return_value=response) as mock_get,
            SuzieqClient(url="http://suzieq:8530/", token="t", namespace="n") as client,
        ):
            client.assert_table("interface")
        assert mock_get.call_args.args[0] == "http://suzieq:8530/api/v2/interface/assert"

    def test_namespace_omitted_when_not_configured(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = []
        with (
            patch.object(sc.httpx.Client, "get", return_value=response) as mock_get,
            SuzieqClient(url="http://suzieq:8530", token="t", namespace=None) as client,
        ):
            client.assert_table("bgp")
        assert "namespace" not in mock_get.call_args.kwargs["params"]

    def test_non_2xx_response_raises_runtime_error(self) -> None:
        response = MagicMock(status_code=401, text="unauthorized")
        with (
            patch.object(sc.httpx.Client, "get", return_value=response),
            SuzieqClient(url="http://suzieq:8530", token="bad", namespace="n") as client,
            pytest.raises(RuntimeError, match="401"),
        ):
            client.assert_table("bgp")


class TestFromEnv:
    def test_reads_configuration_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUZIEQ_REST_URL", "http://host:9999")
        monkeypatch.setenv("SUZIEQ_API_TOKEN", "envtok")
        monkeypatch.setenv("SUZIEQ_NAMESPACE", "envns")
        client = SuzieqClient.from_env()
        assert client.url == "http://host:9999"
        assert client.token == "envtok"
        assert client.namespace == "envns"

    def test_falls_back_to_dev_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("SUZIEQ_REST_URL", "SUZIEQ_API_TOKEN", "SUZIEQ_NAMESPACE"):
            monkeypatch.delenv(var, raising=False)
        client = SuzieqClient.from_env()
        assert client.url == sc.DEFAULT_SUZIEQ_REST_URL
        assert client.namespace == sc.DEFAULT_NAMESPACE
        assert client.token  # dev token present
