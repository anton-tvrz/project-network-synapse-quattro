"""Unit tests for `deploy_configs.deploy_config` (Issue #167).

The script-level SET helper was previously exercised only indirectly via the
mocked `push_via_gnmi` in `test_gnmi_io.py`, so its error handling was untested.
These tests pin the contract the `_gnmi_io` layer relies on:

  - A successful SET returns ``True``.
  - A response without a ``response`` key returns ``False`` (device reached but
    did not acknowledge the SET).
  - Invalid JSON returns ``False`` (bad payload, nothing pushed).
  - Transport errors PROPAGATE — they must not be swallowed into ``False``,
    otherwise `_gnmi_io.deploy_config_via_gnmi` can never classify and rewrap
    them.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pygnmi.client import gNMIException

from network_synapse.scripts import deploy_configs


def _fake_client(set_result: dict) -> MagicMock:
    """Build a gNMIclient factory whose context manager returns a client
    whose ``set`` yields ``set_result``."""
    gc = MagicMock()
    gc.set.return_value = set_result
    factory = MagicMock()
    factory.return_value.__enter__.return_value = gc
    factory.return_value.__exit__.return_value = False
    return factory


@pytest.mark.unit
class TestDeployConfig:
    def test_successful_set_returns_true(self) -> None:
        factory = _fake_client({"response": [{"path": "/", "op": "UPDATE"}]})
        with patch.object(deploy_configs, "gNMIclient", factory):
            assert deploy_configs.deploy_config("spine01", "172.20.20.3", '{"a": 1}') is True

    def test_default_set_uses_update_semantics(self) -> None:
        """Normal deploys merge into the existing config (gNMI update)."""
        factory = _fake_client({"response": [{"path": "/", "op": "UPDATE"}]})
        with patch.object(deploy_configs, "gNMIclient", factory):
            deploy_configs.deploy_config("spine01", "172.20.20.3", '{"a": 1}')

        gc = factory.return_value.__enter__.return_value
        gc.set.assert_called_once_with(update=[("/", {"a": 1})])

    def test_replace_flag_uses_replace_semantics(self) -> None:
        """Rollbacks must RESTORE, not merge (Issue #164).

        A root ``update`` leaves config added by the failed deploy in place;
        ``replace`` returns the device to exactly the backed-up state.
        """
        factory = _fake_client({"response": [{"path": "/", "op": "REPLACE"}]})
        with patch.object(deploy_configs, "gNMIclient", factory):
            result = deploy_configs.deploy_config("spine01", "172.20.20.3", '{"a": 1}', replace=True)

        assert result is True
        gc = factory.return_value.__enter__.return_value
        gc.set.assert_called_once_with(replace=[("/", {"a": 1})])

    def test_missing_response_returns_false(self) -> None:
        factory = _fake_client({"unexpected": True})
        with patch.object(deploy_configs, "gNMIclient", factory):
            assert deploy_configs.deploy_config("spine01", "172.20.20.3", '{"a": 1}') is False

    def test_invalid_json_returns_false(self) -> None:
        # Malformed payload: must never reach the gNMI client.
        factory = _fake_client({"response": [{}]})
        with patch.object(deploy_configs, "gNMIclient", factory):
            assert deploy_configs.deploy_config("spine01", "172.20.20.3", "{not-json") is False
        factory.assert_not_called()

    def test_transport_error_propagates(self) -> None:
        """A gNMI transport error must bubble up, not be swallowed into False.

        `_gnmi_io.deploy_config_via_gnmi` catches this specific exception type to
        rewrap it as RuntimeError; if `deploy_config` swallows it, that
        classification is dead code.
        """
        factory = MagicMock()
        factory.return_value.__enter__.side_effect = gNMIException("UNAVAILABLE", None)
        factory.return_value.__exit__.return_value = False
        with patch.object(deploy_configs, "gNMIclient", factory), pytest.raises(gNMIException):
            deploy_configs.deploy_config("spine01", "172.20.20.3", '{"a": 1}')
