"""Integration tests — verify Infrahub connectivity and Containerlab device state.

Tests are split into two marker categories:

- ``@pytest.mark.integration`` — offline tests (config hygiene checks) that run
  in CI without live infrastructure.
- ``@pytest.mark.live`` — tests requiring running Infrahub, Containerlab, or gNMI.
  These run only on the staging VM after deployment via ``deploy.yml``.

Use ``pytest -m integration`` for offline tests, ``pytest -m live`` for
live-infra tests.
"""

from __future__ import annotations

import json
import os

import pytest

# ---------------------------------------------------------------------------
# Infrahub integration
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_infrahub_connection():
    """Verify that we can reach the Infrahub API and authenticate."""
    from network_synapse.infrahub.client import InfrahubConfigClient

    url = os.getenv("INFRAHUB_URL", "http://localhost:8000")
    token = os.getenv("INFRAHUB_TOKEN", "")

    client = InfrahubConfigClient(url=url, token=token)
    try:
        devices = client.list_devices()
        assert isinstance(devices, list)
        assert len(devices) > 0
    finally:
        client.close()


@pytest.mark.live
def test_infrahub_device_config_retrieval():
    """Verify that we can retrieve a full device config from Infrahub."""
    from network_synapse.infrahub.client import InfrahubConfigClient

    url = os.getenv("INFRAHUB_URL", "http://localhost:8000")
    token = os.getenv("INFRAHUB_TOKEN", "")
    hostname = os.getenv("TEST_DEVICE_HOSTNAME", "spine01")

    client = InfrahubConfigClient(url=url, token=token)
    try:
        config = client.get_device_config(hostname)
        assert config is not None

        bgp_vars = config.to_bgp_template_vars()
        assert bgp_vars.local_asn > 0

        iface_vars = config.to_interface_template_vars()
        assert len(iface_vars.interfaces) > 0
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Containerlab / gNMI integration
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_containerlab_gnmi_connectivity():
    """Verify gNMI connectivity to a Containerlab SR Linux node."""
    from network_synapse.scripts.deploy_configs import validate_gnmi_connection

    device_ip = os.getenv("TEST_DEVICE_IP", "172.20.20.2")
    assert validate_gnmi_connection(device_ip)


@pytest.mark.live
def test_containerlab_bgp_state():
    """Verify BGP sessions are established on a Containerlab device."""
    from network_synapse.scripts.validate_state import check_bgp_summary

    device_ip = os.getenv("TEST_DEVICE_IP", "172.20.20.2")
    assert check_bgp_summary(device_ip)


# ---------------------------------------------------------------------------
# Config hygiene integration (offline — no live infra needed)
# ---------------------------------------------------------------------------

_VALID_BGP = {
    "network-instance": [
        {
            "protocols": {
                "bgp": {
                    "autonomous-system": 65000,
                    "group": [{"group-name": "EBGP"}],
                    "neighbor": [{"peer-address": "10.0.0.1"}],
                }
            }
        }
    ]
}

_VALID_IFACE = {
    "interface": [
        {
            "name": "ethernet-1/1",
            "subinterface": [{"ipv4": {"address": [{"ip-prefix": "10.0.0.0/31"}]}}],
        }
    ]
}

_BAD_BGP = {
    "network-instance": [
        {
            "protocols": {
                "bgp": {
                    "autonomous-system": 0,
                    "group": [{"group-name": "EBGP"}],
                    "neighbor": [{"peer-address": "10.0.0.1"}],
                }
            }
        }
    ]
}


@pytest.mark.integration
def test_hygiene_checker_valid_payload():
    """Test that a well-formed payload passes hygiene checks."""
    from network_synapse.scripts.hygiene_checker import run_hygiene_checks

    assert run_hygiene_checks(json.dumps(_VALID_BGP), json.dumps(_VALID_IFACE))


@pytest.mark.integration
def test_hygiene_checker_invalid_asn():
    """Test that an invalid ASN fails hygiene checks."""
    from network_synapse.scripts.hygiene_checker import validate_bgp_hygiene

    assert not validate_bgp_hygiene(json.dumps(_BAD_BGP))
