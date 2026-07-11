"""Unit tests for the shared `_gnmi_io` helper (Issue #113).

Covers the cross-cutting I/O concerns called out in PR #111:
  - Synchronous pygnmi work runs on a worker thread, not the event loop.
  - Specific transport errors (gNMIException, grpc.RpcError, ConnectionError,
    OSError, TimeoutError) are rewrapped as RuntimeError.
  - The first 'val' update is extracted and returned as a JSON string.
"""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import MagicMock, patch

import grpc
import pytest
from pygnmi.client import gNMIException

from synapse_workers.activities import _gnmi_io


def _make_gnmi_response(payload: dict) -> dict:
    return {"notification": [{"update": [{"val": payload}]}]}


class _FakeGnmiClient:
    """Context-manager fake that records the thread it was entered on."""

    captured_thread_id: int | None = None
    captured_get_kwargs: dict | None = None
    captured_init_kwargs: dict | None = None
    response: dict = _make_gnmi_response({"interfaces": []})

    def __init__(self, *_, **kwargs) -> None:
        _FakeGnmiClient.captured_init_kwargs = kwargs

    def __enter__(self) -> _FakeGnmiClient:
        _FakeGnmiClient.captured_thread_id = threading.get_ident()
        return self

    def __exit__(self, *_) -> bool:
        return False

    def get(self, path: list[str], **kwargs) -> dict:
        _FakeGnmiClient.captured_get_kwargs = {"path": path, **kwargs}
        return self.response


@pytest.mark.unit
class TestFetchConfigViaGnmi:
    """The shared GET helper used by fetch_running_config and backup_running_config."""

    def setup_method(self) -> None:
        _FakeGnmiClient.captured_thread_id = None
        _FakeGnmiClient.captured_get_kwargs = None
        _FakeGnmiClient.captured_init_kwargs = None
        _FakeGnmiClient.response = _make_gnmi_response({"interfaces": [{"name": "ethernet-1/1"}]})

    def test_tls_mode_from_environment_reaches_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GNMI_TLS_MODE must control the transport — insecure is not baked in (Issue #166)."""
        monkeypatch.setenv("GNMI_TLS_MODE", "skip-verify")

        with patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        kwargs = _FakeGnmiClient.captured_init_kwargs
        assert kwargs is not None
        assert kwargs.get("skip_verify") is True
        assert "insecure" not in kwargs

    def test_credentials_resolved_from_environment_when_not_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Secrets come from the worker's environment, not from callers (Issue #166)."""
        monkeypatch.setenv("GNMI_USERNAME", "svc-automation")
        monkeypatch.setenv("GNMI_PASSWORD", "from-env")

        with patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        kwargs = _FakeGnmiClient.captured_init_kwargs
        assert kwargs is not None
        assert kwargs.get("username") == "svc-automation"
        assert kwargs.get("password") == "from-env"

    def test_requests_config_datastore_only(self) -> None:
        """Backups must GET only writable config (Issue #164).

        A default GET of ``/`` returns operational/read-only state (counters,
        oper-state, uptime) that SR Linux rejects on SET — making the backup
        useless as a rollback payload.
        """
        with patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        assert _FakeGnmiClient.captured_get_kwargs is not None
        assert _FakeGnmiClient.captured_get_kwargs.get("datatype") == "config"

    def test_merges_all_updates_across_notifications(self) -> None:
        """Every update in every notification must land in the backup (Issue #164)."""
        _FakeGnmiClient.response = {
            "notification": [
                {"update": [{"path": "", "val": {"interfaces": [{"name": "ethernet-1/1"}]}}]},
                {"update": [{"path": "", "val": {"network-instance": [{"name": "default"}]}}]},
            ]
        }

        with patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient):
            result = asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        assert json.loads(result) == {
            "interfaces": [{"name": "ethernet-1/1"}],
            "network-instance": [{"name": "default"}],
        }

    def test_merges_multiple_updates_within_one_notification(self) -> None:
        _FakeGnmiClient.response = {
            "notification": [
                {
                    "update": [
                        {"path": "/", "val": {"interfaces": []}},
                        {"path": "/", "val": {"system": {"name": {"host-name": "spine01"}}}},
                    ]
                }
            ]
        }

        with patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient):
            result = asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        assert json.loads(result) == {"interfaces": [], "system": {"name": {"host-name": "spine01"}}}

    def test_overlapping_top_level_keys_fail_loud(self) -> None:
        """Two root updates sharing a top-level key cannot be merged shallowly.

        Silently letting the later update win would drop part of the earlier
        one — a corrupted backup that only surfaces at rollback time.
        """
        _FakeGnmiClient.response = {
            "notification": [
                {"update": [{"path": "", "val": {"interfaces": [{"name": "ethernet-1/1"}]}}]},
                {"update": [{"path": "", "val": {"interfaces": [{"name": "ethernet-1/2"}]}}]},
            ]
        }

        with (
            patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient),
            pytest.raises(RuntimeError, match="overlapping"),
        ):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

    def test_non_root_update_path_fails_loud(self) -> None:
        """A subtree-scoped update cannot be merged safely — fail at backup time.

        Failing here aborts the change BEFORE anything is deployed; silently
        mis-nesting the subtree would instead corrupt the rollback payload and
        surface only after a failed deploy (Issue #164).
        """
        _FakeGnmiClient.response = {
            "notification": [{"update": [{"path": "interface[name=ethernet-1/1]", "val": {"mtu": 9000}}]}]
        }

        with (
            patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient),
            pytest.raises(RuntimeError, match="non-root"),
        ):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

    def test_returns_first_val_as_json_string(self) -> None:
        payload = {"interfaces": [{"name": "ethernet-1/1"}]}
        _FakeGnmiClient.response = _make_gnmi_response(payload)

        with patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient):
            result = asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        assert json.loads(result) == payload

    def test_offloads_sync_client_to_worker_thread(self) -> None:
        """The pygnmi client must NOT execute on the event loop thread."""
        main_thread = threading.get_ident()

        with patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        assert _FakeGnmiClient.captured_thread_id is not None
        assert _FakeGnmiClient.captured_thread_id != main_thread, (
            "gNMIclient ran on the event loop thread — to_thread offload is missing"
        )

    def test_unexpected_response_format_raises_runtime_error(self) -> None:
        _FakeGnmiClient.response = {"notification": [{"update": []}]}

        with (
            patch.object(_gnmi_io, "gNMIclient", _FakeGnmiClient),
            pytest.raises(RuntimeError, match="Unexpected gNMI GET format"),
        ):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

    @pytest.mark.parametrize(
        ("exc_factory", "match"),
        [
            (lambda: gNMIException("auth failed", None), "gNMI fetch failed"),
            (lambda: ConnectionError("connection refused"), "gNMI fetch failed"),
            (lambda: OSError("network down"), "gNMI fetch failed"),
            (lambda: TimeoutError("deadline exceeded"), "gNMI fetch failed"),
        ],
    )
    def test_specific_transport_errors_rewrapped_as_runtime_error(self, exc_factory, match) -> None:
        broken = MagicMock()
        broken.return_value.__enter__ = MagicMock(side_effect=exc_factory())
        broken.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(_gnmi_io, "gNMIclient", broken), pytest.raises(RuntimeError, match=match) as exc_info:
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))

        # Chain preserved for diagnostics.
        assert exc_info.value.__cause__ is not None

    def test_grpc_rpc_error_rewrapped_as_runtime_error(self) -> None:
        class _FakeRpcError(grpc.RpcError):
            pass

        broken = MagicMock()
        broken.return_value.__enter__ = MagicMock(side_effect=_FakeRpcError("UNAVAILABLE"))
        broken.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(_gnmi_io, "gNMIclient", broken),
            pytest.raises(RuntimeError, match="gNMI fetch failed"),
        ):
            asyncio.run(_gnmi_io.fetch_config_via_gnmi("spine01", "172.20.20.3"))


@pytest.mark.unit
class TestDeployConfigViaGnmi:
    """The shared SET helper used by deploy_config and rollback_config activities."""

    def test_offloads_push_to_worker_thread(self) -> None:
        main_thread = threading.get_ident()
        captured: dict[str, int | None] = {"thread_id": None}

        def fake_push(**_kwargs) -> bool:
            captured["thread_id"] = threading.get_ident()
            return True

        with patch.object(_gnmi_io, "push_via_gnmi", fake_push):
            result = asyncio.run(_gnmi_io.deploy_config_via_gnmi("spine01", "172.20.20.3", '{"a": 1}'))

        assert result is True
        assert captured["thread_id"] is not None
        assert captured["thread_id"] != main_thread, (
            "push_via_gnmi ran on the event loop thread — to_thread offload is missing"
        )

    def test_passes_credentials_and_payload(self) -> None:
        captured: dict[str, object] = {}

        def fake_push(**kwargs) -> bool:
            captured.update(kwargs)
            return True

        with patch.object(_gnmi_io, "push_via_gnmi", fake_push):
            asyncio.run(
                _gnmi_io.deploy_config_via_gnmi(
                    "spine01",
                    "172.20.20.3",
                    '{"a": 1}',
                    username="u",
                    password="p",
                )
            )

        assert captured == {
            "hostname": "spine01",
            "ip_address": "172.20.20.3",
            "config_payload": '{"a": 1}',
            "username": "u",
            "password": "p",
            "replace": False,
        }

    def test_replace_flag_reaches_push_helper(self) -> None:
        """Rollbacks need replace semantics end-to-end (Issue #164)."""
        captured: dict[str, object] = {}

        def fake_push(**kwargs) -> bool:
            captured.update(kwargs)
            return True

        with patch.object(_gnmi_io, "push_via_gnmi", fake_push):
            asyncio.run(_gnmi_io.deploy_config_via_gnmi("spine01", "172.20.20.3", '{"a": 1}', replace=True))

        assert captured["replace"] is True
