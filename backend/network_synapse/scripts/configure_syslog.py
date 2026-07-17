"""Configure SR Linux remote syslog towards the Loki/Alloy pipeline (Issue #169).

Pushes a ``/system/logging/remote-server`` config via gNMI (YANG-modelled
JSON, merged — never replace) so fabric syslog lands in the Alloy listener
published on the OrbStack host. The default collector address is the
containerlab bridge gateway (172.20.20.1), which is the host as seen from
the SR Linux management network.

SR Linux logs all of its own subsystems at facility ``local6`` with
``match-above informational`` by default, so mirroring that filter on the
remote-server forwards everything the local ``messages`` buffer receives.

Usage:
    uv run python -m network_synapse.scripts.configure_syslog
    uv run python -m network_synapse.scripts.configure_syslog --collector 172.20.20.1 --port 5514
    uv run python -m network_synapse.scripts.configure_syslog --device spine01
"""

from __future__ import annotations

import argparse
import logging
import sys

from pygnmi.client import gNMIclient

from network_synapse.gnmi_settings import gnmi_connection_kwargs, resolve_credentials

logger = logging.getLogger(__name__)

# Containerlab bridge gateway = the OrbStack host, where docker publishes
# the Alloy syslog listener (docker-compose-deps.yml, port 5514/udp).
DEFAULT_COLLECTOR_HOST = "172.20.20.1"
DEFAULT_SYSLOG_PORT = 5514

# Fabric nodes by containerlab DNS name (mgmt IPs are DHCP-assigned).
FABRIC_DEVICES = {
    "spine01": "clab-spine-leaf-lab-spine01",
    "leaf01": "clab-spine-leaf-lab-leaf01",
    "leaf02": "clab-spine-leaf-lab-leaf02",
}


def build_syslog_payload(collector_host: str, syslog_port: int) -> dict:
    """YANG-modelled JSON for ``/system/logging/remote-server``.

    ``network-instance: mgmt`` is required: mgmt0 lives in the mgmt VRF, so
    without it the syslog packets would be routed via the default
    network-instance and never reach the collector.
    """
    return {
        "system": {
            "logging": {
                "remote-server": [
                    {
                        "host": collector_host,
                        "remote-port": syslog_port,
                        "network-instance": "mgmt",
                        "facility": [
                            {
                                "facility-name": "local6",
                                "priority": {"match-above": "informational"},
                            }
                        ],
                    }
                ]
            }
        }
    }


def configure_syslog(
    hostname: str,
    address: str,
    collector_host: str,
    syslog_port: int,
    username: str | None = None,
    password: str | None = None,
    gnmi_port: int = 57400,
) -> bool:
    """Merge the remote-syslog config into a device via gNMI SET.

    Returns ``True`` when the device acknowledged the SET. Transport-level
    failures propagate to the caller (same contract as deploy_configs).
    """
    logger.info(f"Configuring syslog on {hostname} ({address}:{gnmi_port}) -> {collector_host}:{syslog_port}/udp")

    username, password = resolve_credentials(username, password)
    payload = build_syslog_payload(collector_host, syslog_port)

    with gNMIclient(
        target=(address, gnmi_port), username=username, password=password, **gnmi_connection_kwargs()
    ) as gc:
        result = gc.set(update=[("/", payload)])
        if result.get("response"):
            logger.info(f"Remote syslog configured on {hostname}")
            return True
        logger.error(f"Unexpected gNMI response from {hostname}: {result}")
        return False


def main() -> None:
    """Push remote-syslog config to the fabric (all nodes by default)."""
    parser = argparse.ArgumentParser(description="Configure SR Linux remote syslog towards the collector stack")
    parser.add_argument("--collector", default=DEFAULT_COLLECTOR_HOST, help="syslog collector address")
    parser.add_argument("--port", type=int, default=DEFAULT_SYSLOG_PORT, help="syslog collector UDP port")
    parser.add_argument(
        "--device",
        choices=[*FABRIC_DEVICES, "all"],
        default="all",
        help="fabric device to configure (default: all)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    devices = FABRIC_DEVICES if args.device == "all" else {args.device: FABRIC_DEVICES[args.device]}

    results: dict[str, bool] = {}
    for hostname, address in devices.items():
        try:
            results[hostname] = configure_syslog(hostname, address, args.collector, args.port)
        except Exception as e:
            logger.error(f"Failed to configure syslog on {hostname}: {e!s}")
            results[hostname] = False

    for hostname, success in results.items():
        print(f"  {hostname}: {'OK' if success else 'FAILED'}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
