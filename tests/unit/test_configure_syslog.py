"""Unit tests for configure_syslog.py (Issue #169).

The script pushes an SR Linux ``/system/logging/remote-server`` config via
gNMI so fabric syslog lands in the Loki/Alloy pipeline. The YANG payload
shape was verified against a live SR Linux node:

    /system/logging/remote-server[host=*]/remote-port
    /system/logging/remote-server[host=*]/transport
    /system/logging/remote-server[host=*]/network-instance
    /system/logging/remote-server[host=*]/facility[facility-name=*]/priority/match-above

SR Linux logs all of its own subsystems at facility ``local6`` with
``match-above informational`` by default (see the factory ``buffer messages``
config), so mirroring that on the remote-server captures everything.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from network_synapse.scripts.configure_syslog import (
    DEFAULT_COLLECTOR_HOST,
    DEFAULT_SYSLOG_PORT,
    FABRIC_DEVICES,
    build_syslog_payload,
    configure_syslog,
)

# ---------------------------------------------------------------------------
# build_syslog_payload
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildSyslogPayload:
    def test_payload_is_yang_modelled_json(self):
        payload = build_syslog_payload("172.20.20.1", 5514)
        server = payload["system"]["logging"]["remote-server"][0]
        assert server["host"] == "172.20.20.1"
        assert server["remote-port"] == 5514

    def test_syslog_egresses_the_mgmt_network_instance(self):
        """mgmt0 lives in the mgmt VRF; without this the syslog packets
        would be routed via the default network-instance and never arrive."""
        server = build_syslog_payload("172.20.20.1", 5514)["system"]["logging"]["remote-server"][0]
        assert server["network-instance"] == "mgmt"

    def test_captures_srlinux_subsystem_logs(self):
        """SR Linux logs its own subsystems at local6/informational."""
        server = build_syslog_payload("172.20.20.1", 5514)["system"]["logging"]["remote-server"][0]
        facility = server["facility"][0]
        assert facility["facility-name"] == "local6"
        assert facility["priority"] == {"match-above": "informational"}

    def test_defaults_target_clab_gateway(self):
        """The clab bridge gateway (the OrbStack host) forwards to the
        published Alloy listener."""
        assert DEFAULT_COLLECTOR_HOST == "172.20.20.1"
        assert DEFAULT_SYSLOG_PORT == 5514


# ---------------------------------------------------------------------------
# configure_syslog (gNMI SET, mocked transport)
# ---------------------------------------------------------------------------


def _mock_gnmi_client(set_result: dict | None) -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.set.return_value = set_result
    return client


@pytest.mark.unit
class TestConfigureSyslog:
    @patch("network_synapse.scripts.configure_syslog.gNMIclient")
    def test_pushes_merge_update_at_root(self, mock_cls: MagicMock):
        client = _mock_gnmi_client({"response": [{"op": "UPDATE"}]})
        mock_cls.return_value = client

        result = configure_syslog("spine01", "172.20.20.10", "172.20.20.1", 5514)

        assert result is True
        (kwargs_or_args,) = client.set.call_args_list
        update = kwargs_or_args.kwargs.get("update") or kwargs_or_args.args[0]
        path, payload = update[0]
        assert path == "/"
        assert payload["system"]["logging"]["remote-server"][0]["host"] == "172.20.20.1"

    @patch("network_synapse.scripts.configure_syslog.gNMIclient")
    def test_returns_false_when_device_does_not_acknowledge(self, mock_cls: MagicMock):
        mock_cls.return_value = _mock_gnmi_client({})

        assert configure_syslog("spine01", "172.20.20.10", "172.20.20.1", 5514) is False

    @patch("network_synapse.scripts.configure_syslog.resolve_credentials", return_value=("u", "p"))
    @patch("network_synapse.scripts.configure_syslog.gNMIclient")
    def test_credentials_resolved_from_environment(self, mock_cls: MagicMock, mock_resolve: MagicMock):
        """Secrets come from gnmi_settings, never from call sites (Issue #166)."""
        mock_cls.return_value = _mock_gnmi_client({"response": []})

        configure_syslog("spine01", "172.20.20.10", "172.20.20.1", 5514)

        mock_resolve.assert_called_once()
        assert mock_cls.call_args.kwargs["username"] == "u"
        assert mock_cls.call_args.kwargs["password"] == "p"  # noqa: S105 — mock value, not a secret


# ---------------------------------------------------------------------------
# Fabric device inventory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFabricDevices:
    def test_targets_all_fabric_nodes_via_pinned_mgmt_ips(self):
        """The script runs on the macOS host, where containerlab DNS names do
        not resolve (docker-network DNS only) — it must use the static
        mgmt-ipv4 pins from topology.clab.yml (Issue #178)."""
        assert FABRIC_DEVICES == {
            "spine01": "172.20.20.10",
            "leaf01": "172.20.20.11",
            "leaf02": "172.20.20.12",
        }

    def test_fabric_ips_match_topology_pins(self):
        topology_path = Path(__file__).parents[2] / "containerlab" / "topology.clab.yml"
        nodes = yaml.safe_load(topology_path.read_text())["topology"]["nodes"]
        for hostname, address in FABRIC_DEVICES.items():
            assert nodes[hostname]["mgmt-ipv4"] == address
