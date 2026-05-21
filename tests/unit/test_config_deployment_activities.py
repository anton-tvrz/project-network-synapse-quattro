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

    def test_raises_runtime_error_when_push_returns_false(self) -> None:
        async def fake_helper(*_args, **_kwargs) -> bool:
            return False

        with (
            patch.object(config_deployment_activities, "deploy_config_via_gnmi", side_effect=fake_helper),
            pytest.raises(RuntimeError, match="Rollback failed"),
        ):
            asyncio.run(config_deployment_activities.rollback_config("spine01", "172.20.20.3", '{"backup": true}'))
