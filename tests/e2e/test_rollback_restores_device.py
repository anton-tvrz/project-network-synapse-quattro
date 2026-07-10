"""E2E: rollback restores a real SR Linux device to its pre-change config (Issue #164).

Exercises the PRODUCTION backup → deploy → rollback code paths against a live
containerlab node — no mocks. This is the test that would have caught the
GET ``/`` → SET ``/`` round-trip bug: a backup containing operational state is
rejected by SR Linux at rollback time, and a root ``update`` (instead of
``replace``) leaves the bad change in place.

Requires a running SR Linux node with an insecure gNMI listener (the
containerlab default gNMI server is TLS-only; TLS support is tracked in #166).
Configure the target via environment variables::

    TEST_GNMI_IP=172.20.20.2 TEST_GNMI_PORT=57401 pytest tests/e2e -m e2e -k rollback

The test restores the device from its own baseline in a ``finally`` block, so
a failing assertion does not leave the lab node dirty.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket

import pytest

DEVICE_HOSTNAME = os.getenv("TEST_DEVICE_HOSTNAME", "leaf01")
GNMI_IP = os.getenv("TEST_GNMI_IP", "172.20.20.2")
GNMI_PORT = int(os.getenv("TEST_GNMI_PORT", "57401"))
GNMI_USER = os.getenv("TEST_GNMI_USER", "admin")
GNMI_PASS = os.getenv("TEST_GNMI_PASS", "NokiaSrl1!")

# A partial config a bad deploy might push: new interface config that the
# backup does not contain, so a merge-style "rollback" could never remove it.
BOGUS_CHANGE = {
    "interface": [
        {
            "name": "ethernet-1/5",
            "description": "BOGUS-CHANGE-ISSUE-164",
            "admin-state": "disable",
        }
    ]
}


def _gnmi_reachable() -> bool:
    try:
        with socket.create_connection((GNMI_IP, GNMI_PORT), timeout=3):
            return True
    except OSError:
        return False


def _get_running_config() -> dict:
    """Independent read of the device config (not via the code under test)."""
    from pygnmi.client import gNMIclient

    with gNMIclient(
        target=(GNMI_IP, GNMI_PORT),
        username=GNMI_USER,
        password=GNMI_PASS,
        insecure=True,
        gnmi_timeout=15,
    ) as gc:
        return gc.get(path=["/"], datatype="config")["notification"][0]["update"][0]["val"]


@pytest.mark.e2e
def test_backup_then_failed_change_then_rollback_restores_config():
    from network_synapse.scripts.deploy_configs import deploy_config
    from synapse_workers.activities._gnmi_io import fetch_config_via_gnmi

    if not _gnmi_reachable():
        pytest.skip(f"no gNMI listener at {GNMI_IP}:{GNMI_PORT}")

    # 1. Backup via the production helper (config datastore only, all updates).
    backup = asyncio.run(
        fetch_config_via_gnmi(DEVICE_HOSTNAME, GNMI_IP, username=GNMI_USER, password=GNMI_PASS, port=GNMI_PORT)
    )
    baseline = _get_running_config()

    # The backup must be pure config — operational trees in the payload are
    # exactly what made the old rollback fail on SET.
    backup_dict = json.loads(backup)
    operational_markers = [
        k for k in backup_dict if "netconf-monitoring" in k or "yang-library" in k or "platform" in k
    ]
    assert not operational_markers, f"backup contains operational state: {operational_markers}"

    try:
        # 2. Simulate the bad deploy (normal merge semantics, as deploys use).
        assert deploy_config(
            DEVICE_HOSTNAME, GNMI_IP, json.dumps(BOGUS_CHANGE), username=GNMI_USER, password=GNMI_PASS, port=GNMI_PORT
        ), "test change did not deploy"
        broken = _get_running_config()
        assert json.dumps(broken, sort_keys=True) != json.dumps(baseline, sort_keys=True), (
            "test change did not alter the device config"
        )

        # 3. Roll back via the production path: replace, not merge.
        assert deploy_config(
            DEVICE_HOSTNAME, GNMI_IP, backup, username=GNMI_USER, password=GNMI_PASS, port=GNMI_PORT, replace=True
        ), "rollback SET was rejected by the device"
    finally:
        # Restore the baseline even if an assertion above failed.
        deploy_config(
            DEVICE_HOSTNAME,
            GNMI_IP,
            json.dumps(baseline),
            username=GNMI_USER,
            password=GNMI_PASS,
            port=GNMI_PORT,
            replace=True,
        )

    restored = _get_running_config()
    assert json.dumps(restored, sort_keys=True) == json.dumps(baseline, sort_keys=True), (
        "rollback did not restore the pre-change config"
    )
