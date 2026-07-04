"""Unit tests for validation_activities (Issue #95 backfill).

Covers the post-deployment validation activities:
  - `validate_bgp` delegates to `check_bgp_summary` and raises on failure.
  - `validate_interfaces` delegates to `check_interface_state`, logs failing
    details, and raises on failure.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from synapse_workers.activities import validation_activities


@pytest.mark.unit
class TestValidateBgp:
    def test_returns_true_when_sessions_established(self) -> None:
        with patch.object(validation_activities, "check_bgp_summary", return_value=True):
            result = asyncio.run(validation_activities.validate_bgp("leaf01", "172.20.20.5"))

        assert result is True

    def test_raises_runtime_error_when_bgp_check_fails(self) -> None:
        with (
            patch.object(validation_activities, "check_bgp_summary", return_value=False),
            pytest.raises(RuntimeError, match="BGP validation failed on leaf01"),
        ):
            asyncio.run(validation_activities.validate_bgp("leaf01", "172.20.20.5"))


@pytest.mark.unit
class TestValidateInterfaces:
    def test_returns_result_when_interfaces_pass(self) -> None:
        passing_result = {
            "passed": True,
            "device": "172.20.20.5",
            "details": [
                {
                    "name": "ethernet-1/1",
                    "status": "pass",
                    "reason": "",
                    "admin_state": "enable",
                    "oper_state": "up",
                }
            ],
        }
        with patch.object(validation_activities, "check_interface_state", return_value=passing_result):
            result = asyncio.run(
                validation_activities.validate_interfaces(
                    "leaf01", "172.20.20.5", [{"name": "ethernet-1/1", "enabled": True}]
                )
            )

        assert result == passing_result

    def test_raises_runtime_error_and_logs_failing_details(self) -> None:
        failing_result = {
            "passed": False,
            "device": "172.20.20.5",
            "details": [
                {
                    "name": "ethernet-1/1",
                    "status": "fail",
                    "reason": "admin-state is disable, expected enable",
                    "admin_state": "disable",
                    "oper_state": "down",
                },
                {
                    "name": "ethernet-1/2",
                    "status": "pass",
                    "reason": "",
                    "admin_state": "enable",
                    "oper_state": "up",
                },
            ],
        }
        with (
            patch.object(validation_activities, "check_interface_state", return_value=failing_result),
            pytest.raises(RuntimeError, match="Interface validation failed on leaf01"),
        ):
            asyncio.run(
                validation_activities.validate_interfaces(
                    "leaf01",
                    "172.20.20.5",
                    [{"name": "ethernet-1/1", "enabled": True}, {"name": "ethernet-1/2", "enabled": True}],
                )
            )
