"""Unit tests for drift_activities (Issue #113).

Focus on the hardened gNMI I/O contract:
  - `fetch_running_config` delegates to the shared `_gnmi_io` helper.
  - Transport errors raised by the helper propagate as RuntimeError.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from synapse_workers.activities import drift_activities


@pytest.mark.unit
class TestFetchRunningConfig:
    def test_delegates_to_shared_helper(self) -> None:
        async def fake_helper(device_hostname, ip_address, *_args, **_kwargs):
            assert device_hostname == "spine01"
            assert ip_address == "172.20.20.3"
            return '{"ok": true}'

        with patch.object(drift_activities, "fetch_config_via_gnmi", side_effect=fake_helper):
            result = asyncio.run(drift_activities.fetch_running_config("spine01", "172.20.20.3"))

        assert result == '{"ok": true}'

    def test_propagates_runtime_error_from_helper(self) -> None:
        async def boom(*_args, **_kwargs) -> str:
            raise RuntimeError("gNMI fetch failed for spine01: connection refused")

        with (
            patch.object(drift_activities, "fetch_config_via_gnmi", side_effect=boom),
            pytest.raises(RuntimeError, match="gNMI fetch failed"),
        ):
            asyncio.run(drift_activities.fetch_running_config("spine01", "172.20.20.3"))
