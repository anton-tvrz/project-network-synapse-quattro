"""Unit tests for config_deployment_activities (Issue #113).

Both `deploy_config` and `rollback_config` must offload the synchronous
pygnmi SET via the shared helper so the activity coroutine doesn't block
the Temporal worker event loop.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from synapse_workers.activities import config_deployment_activities


@pytest.mark.unit
class TestDeployConfig:
    def test_delegates_to_shared_helper_and_returns_true_on_success(self) -> None:
        async def fake_helper(device_hostname, ip_address, config_payload, **_kwargs):
            assert device_hostname == "spine01"
            assert ip_address == "172.20.20.3"
            assert config_payload == '{"a": 1}'
            return True

        with patch.object(config_deployment_activities, "deploy_config_via_gnmi", side_effect=fake_helper):
            result = asyncio.run(config_deployment_activities.deploy_config("spine01", "172.20.20.3", '{"a": 1}'))

        assert result is True

    def test_raises_runtime_error_when_push_returns_false(self) -> None:
        async def fake_helper(*_args, **_kwargs) -> bool:
            return False

        with (
            patch.object(config_deployment_activities, "deploy_config_via_gnmi", side_effect=fake_helper),
            pytest.raises(RuntimeError, match="Config deployment failed"),
        ):
            asyncio.run(config_deployment_activities.deploy_config("spine01", "172.20.20.3", '{"a": 1}'))


@pytest.mark.unit
class TestRollbackConfig:
    def test_delegates_to_shared_helper_and_returns_true_on_success(self) -> None:
        async def fake_helper(device_hostname, ip_address, config_payload, **_kwargs):
            assert device_hostname == "spine01"
            assert ip_address == "172.20.20.3"
            assert config_payload == '{"backup": true}'
            return True

        with patch.object(config_deployment_activities, "deploy_config_via_gnmi", side_effect=fake_helper):
            result = asyncio.run(
                config_deployment_activities.rollback_config("spine01", "172.20.20.3", '{"backup": true}')
            )

        assert result is True

    def test_rollback_uses_replace_semantics(self) -> None:
        """Rollback must restore the backup exactly, not merge into the broken state (Issue #164)."""
        captured: dict[str, object] = {}

        async def fake_helper(*_args, **kwargs) -> bool:
            captured.update(kwargs)
            return True

        with patch.object(config_deployment_activities, "deploy_config_via_gnmi", side_effect=fake_helper):
            asyncio.run(config_deployment_activities.rollback_config("spine01", "172.20.20.3", '{"backup": true}'))

        assert captured.get("replace") is True

    def test_deploy_uses_merge_semantics(self) -> None:
        """Forward deploys must NOT replace: generated configs are partial (interfaces + BGP)."""
        captured: dict[str, object] = {}

        async def fake_helper(*_args, **kwargs) -> bool:
            captured.update(kwargs)
            return True

        with patch.object(config_deployment_activities, "deploy_config_via_gnmi", side_effect=fake_helper):
            asyncio.run(config_deployment_activities.deploy_config("spine01", "172.20.20.3", '{"a": 1}'))

        assert captured.get("replace", False) is False

    def test_raises_runtime_error_when_push_returns_false(self) -> None:
        async def fake_helper(*_args, **_kwargs) -> bool:
            return False

        with (
            patch.object(config_deployment_activities, "deploy_config_via_gnmi", side_effect=fake_helper),
            pytest.raises(RuntimeError, match="Rollback failed"),
        ):
            asyncio.run(config_deployment_activities.rollback_config("spine01", "172.20.20.3", '{"backup": true}'))
