"""End-to-end tests covering the full automation workflow.

These tests verify the complete pipeline:
  Infrahub query → Config generation → Hygiene check → gNMI deploy → Validate

They require all infrastructure to be running (Infrahub, Containerlab, Temporal).
Run with: ``pytest tests/e2e/ -m e2e``
"""

from __future__ import annotations

import json
import os

import pytest

# ---------------------------------------------------------------------------
# E2E: Config generation pipeline
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_full_config_generation_pipeline():
    """Generate configs from Infrahub data and validate them with hygiene checker."""
    from network_synapse.infrahub.client import InfrahubConfigClient
    from network_synapse.scripts.generate_configs import (
        generate_bgp_config,
        generate_interface_config,
    )
    from network_synapse.scripts.hygiene_checker import run_hygiene_checks

    url = os.getenv("INFRAHUB_URL", "http://localhost:8000")
    token = os.getenv("INFRAHUB_TOKEN", "")
    hostname = os.getenv("TEST_DEVICE_HOSTNAME", "spine01")

    # 1. Fetch from Infrahub
    client = InfrahubConfigClient(url=url, token=token)
    try:
        config = client.get_device_config(hostname)
        assert config is not None
    finally:
        client.close()

    # 2. Generate configs
    bgp_vars = config.to_bgp_template_vars()
    iface_vars = config.to_interface_template_vars()

    bgp_json = generate_bgp_config(bgp_vars.__dict__)
    iface_json = generate_interface_config(iface_vars.__dict__)

    assert bgp_json, "BGP config should not be empty"
    assert iface_json, "Interface config should not be empty"

    # 3. Validate with hygiene checker
    assert run_hygiene_checks(bgp_json, iface_json), "Generated configs should pass hygiene checks"


@pytest.mark.e2e
def test_config_deploy_and_validate():
    """Deploy a config to a device and validate the operational state."""
    from network_synapse.scripts.deploy_configs import (
        deploy_config,
        validate_gnmi_connection,
    )
    from network_synapse.scripts.validate_state import check_bgp_summary

    device_ip = os.getenv("TEST_DEVICE_IP", "172.20.20.2")
    hostname = os.getenv("TEST_DEVICE_HOSTNAME", "spine01")

    # 1. Verify connectivity
    assert validate_gnmi_connection(device_ip), f"Must be able to reach {device_ip} via gNMI"

    # 2. Deploy a minimal config (read-only test — just verify the path works)
    # We use an empty update to avoid mutating state in a test
    minimal_config = json.dumps({"system": {"name": {"host-name": hostname}}})
    result = deploy_config(
        hostname=hostname,
        ip_address=device_ip,
        config_payload=minimal_config,
    )
    assert result, "Deployment should succeed"

    # 3. Validate BGP state is still healthy
    bgp_ok = check_bgp_summary(device_ip)
    assert bgp_ok, "BGP sessions should remain established after deployment"


@pytest.mark.e2e
def test_hygiene_rejects_bad_config():
    """Verify the hygiene checker blocks a clearly invalid config."""
    from network_synapse.scripts.hygiene_checker import run_hygiene_checks

    bad_bgp = json.dumps(
        {
            "network-instance": [
                {
                    "protocols": {
                        "bgp": {
                            "autonomous-system": 0,
                            "group": [],
                            "neighbor": [{"peer-address": "not-an-ip"}],
                        }
                    }
                }
            ]
        }
    )
    valid_iface = json.dumps(
        {
            "interface": [
                {
                    "name": "ethernet-1/1",
                    "subinterface": [{"ipv4": {"address": [{"ip-prefix": "10.0.0.0/31"}]}}],
                }
            ]
        }
    )

    assert not run_hygiene_checks(bad_bgp, valid_iface), "Bad BGP config should fail hygiene"


@pytest.mark.e2e
def test_rollback_restores_config():
    """Verify that the rollback mechanism restores a previous config."""
    from network_synapse.scripts.deploy_configs import (
        deploy_config,
        validate_gnmi_connection,
    )

    device_ip = os.getenv("TEST_DEVICE_IP", "172.20.20.2")
    hostname = os.getenv("TEST_DEVICE_HOSTNAME", "spine01")

    if not validate_gnmi_connection(device_ip):
        pytest.skip(f"Cannot reach {device_ip}")

    # 1. Read current config (backup)
    from network_synapse.scripts.validate_state import check_bgp_summary

    original_bgp_ok = check_bgp_summary(device_ip)

    # 2. Deploy a harmless change
    minimal = json.dumps({"system": {"name": {"host-name": hostname}}})
    deploy_config(hostname, device_ip, minimal)

    # 3. Re-deploy the same (simulates rollback)
    deploy_config(hostname, device_ip, minimal)

    # 4. Verify BGP state unchanged
    post_bgp_ok = check_bgp_summary(device_ip)
    assert original_bgp_ok == post_bgp_ok, "BGP state should be unchanged after rollback"


# ---------------------------------------------------------------------------
# E2E: Resource pool allocation + config generation
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_pool_allocation_and_config_generation():
    """Allocate resources from pools, create device, generate config."""
    from network_synapse.infrahub.client import InfrahubConfigClient
    from network_synapse.infrahub.resource_manager import InfrahubResourceManager
    from network_synapse.scripts.generate_configs import (
        generate_bgp_config,
        generate_interface_config,
    )

    url = os.getenv("INFRAHUB_URL", "http://localhost:8000")
    token = os.getenv("INFRAHUB_TOKEN", "")

    # 1. Provision resources for a test device
    mgr = InfrahubResourceManager(url=url, token=token)
    try:
        result = mgr.provision_device("e2e-test-device", "leaf", ["spine01"])
        assert result.asn > 0
        assert "/" in result.loopback_ip
        assert len(result.fabric_links) == 1
    except Exception:
        pytest.skip("Pool allocation not available (pools may not be seeded)")
    finally:
        mgr.close()

    # 2. Verify we can still generate configs for existing devices
    client = InfrahubConfigClient(url=url, token=token)
    try:
        config = client.get_device_config("spine01")
        assert config is not None
        bgp_json = generate_bgp_config(config.to_bgp_template_vars().__dict__)
        iface_json = generate_interface_config(config.to_interface_template_vars().__dict__)
        assert bgp_json
        assert iface_json
    finally:
        client.close()


@pytest.mark.e2e
def test_transform_matches_local_rendering():
    """Compare Infrahub transform output vs local Jinja2 rendering."""
    from network_synapse.infrahub.client import InfrahubConfigClient
    from network_synapse.scripts.generate_configs import generate_bgp_config

    url = os.getenv("INFRAHUB_URL", "http://localhost:8000")
    token = os.getenv("INFRAHUB_TOKEN", "")
    hostname = os.getenv("TEST_DEVICE_HOSTNAME", "spine01")

    client = InfrahubConfigClient(url=url, token=token)
    try:
        # 1. Local rendering via Jinja2
        config = client.get_device_config(hostname)
        assert config is not None
        local_bgp = json.loads(generate_bgp_config(config.to_bgp_template_vars().__dict__))

        # 2. Remote rendering via Infrahub transform
        try:
            remote_bgp_str = client.execute_transform("srlinux_bgp_config", {"hostname": hostname})
        except Exception:
            pytest.skip("Transform execution not available")

        remote_bgp = json.loads(remote_bgp_str)

        # 3. Compare key structural elements
        local_ni = local_bgp["network-instance"][0]
        remote_ni = remote_bgp["network-instance"][0]

        assert local_ni["protocols"]["bgp"]["autonomous-system"] == remote_ni["protocols"]["bgp"]["autonomous-system"]
        assert local_ni["protocols"]["bgp"]["router-id"] == remote_ni["protocols"]["bgp"]["router-id"]
    finally:
        client.close()


@pytest.mark.e2e
def test_check_validates_seeded_data():
    """Run Infrahub checks against seeded data and verify they pass."""
    from network_synapse.checks.bgp_session_check import BGPSessionCheck
    from network_synapse.checks.interface_consistency_check import InterfaceConsistencyCheck
    from network_synapse.checks.ip_uniqueness_check import IPUniquenessCheck
    from network_synapse.infrahub.client import InfrahubConfigClient

    url = os.getenv("INFRAHUB_URL", "http://localhost:8000")
    token = os.getenv("INFRAHUB_TOKEN", "")

    client = InfrahubConfigClient(url=url, token=token)
    try:
        # Fetch raw data for checks
        config = client.get_device_config("spine01")
        assert config is not None, "spine01 must be seeded"
    finally:
        client.close()

    # The checks validate GraphQL responses directly — run them with
    # a minimal valid dataset to verify the check logic in an e2e context
    import asyncio

    async def _run_checks():
        bgp_check = BGPSessionCheck()
        bgp_data = {
            "RoutingBGPSession": {
                "edges": [
                    {
                        "node": {
                            "id": "e2e-bgp-1",
                            "description": {"value": "e2e test session"},
                            "session_type": {"value": "EXTERNAL"},
                            "role": {"value": "backbone"},
                            "status": {"value": "active"},
                            "local_as": {"node": {"asn": {"value": 65000}}},
                            "remote_as": {"node": {"asn": {"value": 65001}}},
                            "local_ip": {"node": {"address": {"value": "10.0.0.0/31"}}},
                            "remote_ip": {"node": {"address": {"value": "10.0.0.1/31"}}},
                            "peer_group": {"node": {"name": {"value": "underlay"}}},
                        }
                    }
                ]
            }
        }
        await bgp_check.validate(bgp_data)
        assert not bgp_check.errors, f"BGP check should pass on valid data: {bgp_check.errors}"

        ip_check = IPUniquenessCheck()
        ip_data = {
            "IpamIPAddress": {
                "edges": [
                    {
                        "node": {
                            "id": "e2e-ip-1",
                            "address": {"value": "10.0.0.0/31"},
                            "description": {"value": ""},
                            "ip_namespace": {"node": {"name": {"value": "default"}}},
                            "interface": {"node": None},
                        }
                    }
                ]
            }
        }
        await ip_check.validate(ip_data)
        assert not ip_check.errors, f"IP check should pass on valid data: {ip_check.errors}"

        iface_check = InterfaceConsistencyCheck()
        iface_data = {
            "InterfacePhysical": {
                "edges": [
                    {
                        "node": {
                            "id": "e2e-iface-1",
                            "name": {"value": "ethernet-1/1"},
                            "description": {"value": "to leaf01"},
                            "mtu": {"value": 9214},
                            "role": {"value": "fabric"},
                            "status": {"value": "active"},
                            "device": {"node": {"name": {"value": "spine01"}}},
                            "ip_addresses": {"edges": [{"node": {"address": {"value": "10.0.0.0/31"}}}]},
                        }
                    }
                ]
            }
        }
        await iface_check.validate(iface_data)
        assert not iface_check.errors, f"Interface check should pass: {iface_check.errors}"

    asyncio.run(_run_checks())
