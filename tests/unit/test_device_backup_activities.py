"""Unit tests for device_backup_activities (Issue #113).

`backup_running_config` should delegate to the shared gNMI I/O helper rather
than re-implement the pygnmi GET pattern.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from synapse_workers.activities import device_backup_activities


@pytest.mark.unit
class TestBackupRunningConfig:
    def test_delegates_to_shared_helper(self) -> None:
        async def fake_helper(device_hostname, ip_address, *_args, **_kwargs):
            assert device_hostname == "leaf01"
            assert ip_address == "172.20.20.2"
            return '{"backup": true}'

        with patch.object(device_backup_activities, "fetch_config_via_gnmi", side_effect=fake_helper):
            result = asyncio.run(device_backup_activities.backup_running_config("leaf01", "172.20.20.2"))

        assert result == '{"backup": true}'

    def test_propagates_runtime_error_from_helper(self) -> None:
        async def boom(*_args, **_kwargs) -> str:
            raise RuntimeError("gNMI fetch failed for leaf01: deadline exceeded")

        with (
            patch.object(device_backup_activities, "fetch_config_via_gnmi", side_effect=boom),
            pytest.raises(RuntimeError, match="gNMI fetch failed"),
        ):
            asyncio.run(device_backup_activities.backup_running_config("leaf01", "172.20.20.2"))
