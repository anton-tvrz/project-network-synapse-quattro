#!/usr/bin/env python3
"""Seed data / initial population script for Infrahub source of truth.

Reads seed data from infrahub/data/seed_data.yml and creates objects in Infrahub
via the GraphQL API. Supports idempotency via upsert mutations.

Usage:
    python populate_sot.py [--url http://localhost:8000] [--token <api-token>] [--dry-run]

Environment Variables:
    INFRAHUB_URL:   Infrahub server URL (default: http://localhost:8000)
    INFRAHUB_TOKEN: API token for authentication (optional for local dev)

Object creation order (respecting dependencies):
    1. Organization (Manufacturer)
    2. Location (Site)
    3. Platform
    4. Device Types
    5. Autonomous Systems
    6. IP Namespace (default)
    7. VRFs
    8. Devices (requires: location, platform, device_type, asn)
    9. IP Prefixes
    10. IP Addresses
    11. Interfaces (requires: device, ip_addresses)
    12. BGP Peer Groups (requires: vrf)
    13. BGP Sessions (requires: device, local_as, remote_as, local_ip, remote_ip)
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_project_root() -> Path:
    """Find the project root directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    return current.parent.parent.parent


def graphql(client: httpx.Client, base_url: str, query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query/mutation."""
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    resp = client.post(f"{base_url}/graphql", json=payload, timeout=30.0)
    data = resp.json()

    if data.get("errors"):
        error_msgs = [e.get("message", str(e)) for e in data["errors"]]
        raise RuntimeError(f"GraphQL errors: {'; '.join(error_msgs)}")

    return data.get("data", {})


def get_or_create(
    client: httpx.Client,
    base_url: str,
    type_name: str,
    lookup_field: str,
    lookup_value: str | int,
    create_data: dict,
    label: str = "",
) -> str:
    """Get existing object ID or create new one. Returns the object ID."""
    display = label or f"{type_name}:{lookup_value}"

    # Format the lookup value — integers (BigInt) must not be quoted
    formatted_value = str(lookup_value) if isinstance(lookup_value, int) else f'"{lookup_value}"'

    # Query for existing object
    query = f"""
    query {{
        {type_name}(
            {lookup_field}__value: {formatted_value}
        ) {{
            edges {{
                node {{
                    id
                }}
            }}
        }}
    }}
    """
    result = graphql(client, base_url, query)
    edges = result.get(type_name, {}).get("edges", [])

    if edges:
        obj_id = edges[0]["node"]["id"]
        print(f"  ✓ {display} (exists: {obj_id[:8]}...)")
        return obj_id

    # Create new object
    # Use GraphQL variables for input data (Infrahub accepts JSON-style via variables)
    mutation_with_var = f"""
    mutation Create($data: {type_name}CreateInput!) {{
        {type_name}Create(data: $data) {{
            ok
            object {{
                id
                display_label
            }}
        }}
    }}
    """
    result = graphql(client, base_url, mutation_with_var, variables={"data": create_data})
    create_result = result.get(f"{type_name}Create", {})

    if create_result.get("ok"):
        obj_id = create_result["object"]["id"]
        dl = create_result["object"].get("display_label", "")
        print(f"  ✅ {display} (created: {obj_id[:8]}... {dl})")
        return obj_id
    raise RuntimeError(f"Failed to create {display}: {result}")


# ---------------------------------------------------------------------------
# Population functions
# ---------------------------------------------------------------------------


def populate_manufacturer(client: httpx.Client, base_url: str, seed: dict) -> str:
    """Create the Nokia manufacturer."""
    mfg = seed["manufacturer"]
    return get_or_create(
        client,
        base_url,
        "OrganizationManufacturer",
        "name",
        mfg["name"],
        {"name": {"value": mfg["name"]}, "description": {"value": mfg["description"]}},
        label=f"Manufacturer: {mfg['name']}",
    )


def populate_location(client: httpx.Client, base_url: str, seed: dict) -> str:
    """Create the lab location."""
    loc = seed["location"]
    return get_or_create(
        client,
        base_url,
        "LocationSite",
        "name",
        loc["name"],
        {
            "name": {"value": loc["name"]},
            "shortname": {"value": loc["shortname"]},
            "description": {"value": loc["description"]},
        },
        label=f"Location: {loc['name']}",
    )


def populate_platform(client: httpx.Client, base_url: str, seed: dict, manufacturer_id: str) -> str:
    """Create the SR Linux platform."""
    plat = seed["platform"]
    return get_or_create(
        client,
        base_url,
        "DcimPlatform",
        "name",
        plat["name"],
        {
            "name": {"value": plat["name"]},
            "description": {"value": plat["description"]},
            "nornir_platform": {"value": plat["nornir_platform"]},
            "napalm_driver": {"value": plat["napalm_driver"]},
            "containerlab_os": {"value": plat["containerlab_os"]},
            "ansible_network_os": {"value": plat["ansible_network_os"]},
            "netmiko_device_type": {"value": plat["netmiko_device_type"]},
            "manufacturer": {"id": manufacturer_id},
        },
        label=f"Platform: {plat['name']}",
    )


def populate_device_types(
    client: httpx.Client, base_url: str, seed: dict, manufacturer_id: str, platform_id: str
) -> dict[str, str]:
    """Create device types. Returns {name: id} mapping."""
    dt_ids = {}
    for dt in seed["device_types"]:
        dt_id = get_or_create(
            client,
            base_url,
            "DcimDeviceType",
            "name",
            dt["name"],
            {
                "name": {"value": dt["name"]},
                "description": {"value": dt["description"]},
                "part_number": {"value": dt["part_number"]},
                "manufacturer": {"id": manufacturer_id},
                "platform": {"id": platform_id},
            },
            label=f"DeviceType: {dt['name']}",
        )
        dt_ids[dt["name"]] = dt_id
    return dt_ids


def populate_autonomous_systems(
    client: httpx.Client, base_url: str, seed: dict, organization_id: str
) -> dict[int, str]:
    """Create autonomous systems. Returns {asn: id} mapping."""
    as_ids = {}
    for asys in seed["autonomous_systems"]:
        as_id = get_or_create(
            client,
            base_url,
            "RoutingAutonomousSystem",
            "asn",
            asys["asn"],
            {
                "name": {"value": asys["name"]},
                "asn": {"value": asys["asn"]},
                "description": {"value": asys["description"]},
                "organization": {"id": organization_id},
            },
            label=f"AS{asys['asn']}: {asys['name']}",
        )
        as_ids[asys["asn"]] = as_id
    return as_ids


def populate_namespace(client: httpx.Client, base_url: str) -> str:
    """Ensure the default IPAM namespace exists."""
    return get_or_create(
        client,
        base_url,
        "IpamNamespace",
        "name",
        "default",
        {
            "name": {"value": "default"},
            "description": {"value": "Default IP namespace"},
        },
        label="Namespace: default",
    )


def populate_vrfs(client: httpx.Client, base_url: str, seed: dict, namespace_id: str) -> dict[str, str]:
    """Create VRFs. Returns {name: id} mapping."""
    vrf_ids = {}
    for vrf in seed.get("vrfs", []):
        vrf_id = get_or_create(
            client,
            base_url,
            "IpamVRF",
            "name",
            vrf["name"],
            {
                "name": {"value": vrf["name"]},
                "description": {"value": vrf["description"]},
                "namespace": {"id": namespace_id},
            },
            label=f"VRF: {vrf['name']}",
        )
        vrf_ids[vrf["name"]] = vrf_id
    return vrf_ids


def populate_devices(
    client: httpx.Client,
    base_url: str,
    seed: dict,
    location_id: str,
    platform_id: str,
    dt_ids: dict[str, str],
    as_ids: dict[int, str],
) -> dict[str, str]:
    """Create devices. Returns {name: id} mapping."""
    device_ids = {}
    for dev in seed["devices"]:
        create_data: dict[str, Any] = {
            "name": {"value": dev["name"]},
            "description": {"value": dev["description"]},
            "status": {"value": dev["status"]},
            "role": {"value": dev["role"]},
            "management_ip": {"value": dev["management_ip"]},
            "lab_node_name": {"value": dev["lab_node_name"]},
            "location": {"id": location_id},
            "platform": {"id": platform_id},
        }

        if dev["device_type"] in dt_ids:
            create_data["device_type"] = {"id": dt_ids[dev["device_type"]]}

        if dev["asn"] in as_ids:
            create_data["asn"] = {"id": as_ids[dev["asn"]]}

        dev_id = get_or_create(
            client,
            base_url,
            "DcimDevice",
            "name",
            dev["name"],
            create_data,
            label=f"Device: {dev['name']}",
        )
        device_ids[dev["name"]] = dev_id
    return device_ids


def populate_ip_addresses(client: httpx.Client, base_url: str, seed: dict, namespace_id: str) -> dict[str, str]:
    """Create IP addresses from interface definitions. Returns {ip: id} mapping."""
    ip_ids = {}
    for iface in seed.get("interfaces", []):
        ip = iface.get("ip_address")
        if not ip or ip in ip_ids:
            continue

        # IP address in Infrahub uses IpamIPAddress with address attribute
        ip_id = get_or_create(
            client,
            base_url,
            "IpamIPAddress",
            "address",
            ip,
            {
                "address": {"value": ip},
                "description": {"value": iface.get("description", "")},
                "ip_namespace": {"id": namespace_id},
            },
            label=f"IP: {ip}",
        )
        ip_ids[ip] = ip_id
    return ip_ids


def populate_interfaces(
    client: httpx.Client,
    base_url: str,
    seed: dict,
    device_ids: dict[str, str],
    ip_ids: dict[str, str],
) -> dict[str, str]:
    """Create interfaces. Returns {device:ifname: id} mapping."""
    iface_ids = {}
    for iface in seed.get("interfaces", []):
        dev_name = iface["device"]
        if_name = iface["name"]
        key = f"{dev_name}:{if_name}"

        if dev_name not in device_ids:
            print(f"  ⚠  Skipping {key}: device {dev_name} not found")
            continue

        create_data: dict[str, Any] = {
            "name": {"value": if_name},
            "description": {"value": iface.get("description", "")},
            "device": {"id": device_ids[dev_name]},
            "status": {"value": "active"},
        }

        if iface.get("mtu"):
            create_data["mtu"] = {"value": iface["mtu"]}

        if iface.get("role"):
            create_data["role"] = {"value": iface["role"]}

        if iface.get("ip_address") and iface["ip_address"] in ip_ids:
            create_data["ip_addresses"] = [{"id": ip_ids[iface["ip_address"]]}]

        # Use name + device filter for lookup to avoid duplicates
        # Since we can't easily filter by both name and device in the simple get_or_create,
        # we'll query specifically
        query = f"""
        query {{
            InterfacePhysical(
                name__value: "{if_name}"
                device__ids: ["{device_ids[dev_name]}"]
            ) {{
                edges {{
                    node {{ id }}
                }}
            }}
        }}
        """
        result = graphql(client, base_url, query)
        edges = result.get("InterfacePhysical", {}).get("edges", [])

        if edges:
            iface_id = edges[0]["node"]["id"]
            print(f"  ✓ Interface: {key} (exists: {iface_id[:8]}...)")
        else:
            mutation = """
            mutation Create($data: InterfacePhysicalCreateInput!) {
                InterfacePhysicalCreate(data: $data) {
                    ok
                    object { id display_label }
                }
            }
            """
            result = graphql(client, base_url, mutation, variables={"data": create_data})
            create_result = result.get("InterfacePhysicalCreate", {})
            if create_result.get("ok"):
                iface_id = create_result["object"]["id"]
                print(f"  ✅ Interface: {key} (created: {iface_id[:8]}...)")
            else:
                print(f"  ❌ Interface: {key} failed: {result}")
                continue

        iface_ids[key] = iface_id
    return iface_ids


def populate_bgp_sessions(
    client: httpx.Client,
    base_url: str,
    seed: dict,
    device_ids: dict[str, str],
    as_ids: dict[int, str],
    ip_ids: dict[str, str],
    vrf_ids: dict[str, str],
) -> None:
    """Create BGP sessions."""
    for session in seed.get("bgp_sessions", []):
        desc = session["description"]

        create_data: dict[str, Any] = {
            "description": {"value": desc},
            "session_type": {"value": session["session_type"]},
            "role": {"value": session["role"]},
            "status": {"value": "active"},
        }

        # Device relationship
        if session["local_device"] in device_ids:
            create_data["device"] = {"id": device_ids[session["local_device"]]}

        # AS relationships
        if session["local_as"] in as_ids:
            create_data["local_as"] = {"id": as_ids[session["local_as"]]}
        if session["remote_as"] in as_ids:
            create_data["remote_as"] = {"id": as_ids[session["remote_as"]]}

        # IP relationships
        if session["local_ip"] in ip_ids:
            create_data["local_ip"] = {"id": ip_ids[session["local_ip"]]}
        if session["remote_ip"] in ip_ids:
            create_data["remote_ip"] = {"id": ip_ids[session["remote_ip"]]}

        # VRF relationship (BGP sessions inherit from RoutingProtocol which requires VRF)
        if "default" in vrf_ids:
            create_data["vrf"] = {"id": vrf_ids["default"]}

        # Check if session exists by description
        query = f"""
        query {{
            RoutingBGPSession(description__value: "{desc}") {{
                edges {{ node {{ id }} }}
            }}
        }}
        """
        result = graphql(client, base_url, query)
        edges = result.get("RoutingBGPSession", {}).get("edges", [])

        if edges:
            print(f"  ✓ BGP Session: {desc} (exists)")
        else:
            mutation = """
            mutation Create($data: RoutingBGPSessionCreateInput!) {
                RoutingBGPSessionCreate(data: $data) {
                    ok
                    object { id display_label }
                }
            }
            """
            result = graphql(client, base_url, mutation, variables={"data": create_data})
            create_result = result.get("RoutingBGPSessionCreate", {})
            if create_result.get("ok"):
                print(f"  ✅ BGP Session: {desc} (created)")
            else:
                print(f"  ❌ BGP Session: {desc} failed: {result}")


# ---------------------------------------------------------------------------
# Resource pool population (opt-in via --with-pools)
# ---------------------------------------------------------------------------


def populate_ip_prefix_pools(
    client: httpx.Client,
    base_url: str,
    pool_defs: dict,
    prefix_ids: dict[str, str],
) -> dict[str, str]:
    """Create IP prefix pools. Returns {pool_name: pool_id} mapping."""
    pool_ids = {}
    for pool in pool_defs.get("ip_prefix_pools", []):
        name = pool["name"]

        # Resolve resource prefix IDs
        resource_ids = []
        for res in pool.get("resources", []):
            prefix = res["prefix"]
            if prefix in prefix_ids:
                resource_ids.append(prefix_ids[prefix])
            else:
                print(f"  ⚠  Pool '{name}': resource prefix '{prefix}' not found, skipping")

        if not resource_ids:
            print(f"  ⚠  Pool '{name}': no valid resources, skipping")
            continue

        create_data: dict[str, Any] = {
            "name": {"value": name},
            "description": {"value": pool.get("description", "")},
            "default_prefix_length": {"value": pool["default_prefix_length"]},
            "resources": [{"id": rid} for rid in resource_ids],
        }

        pool_id = get_or_create(
            client,
            base_url,
            "CoreIPPrefixPool",
            "name",
            name,
            create_data,
            label=f"IPPrefixPool: {name}",
        )
        pool_ids[name] = pool_id
    return pool_ids


def populate_ip_address_pools(
    client: httpx.Client,
    base_url: str,
    pool_defs: dict,
    prefix_ids: dict[str, str],
) -> dict[str, str]:
    """Create IP address pools. Returns {pool_name: pool_id} mapping."""
    pool_ids = {}
    for pool in pool_defs.get("ip_address_pools", []):
        name = pool["name"]

        # Resolve resource IDs (can reference prefixes directly)
        resource_ids = []
        for res in pool.get("resources", []):
            if "prefix" in res and res["prefix"] in prefix_ids:
                resource_ids.append(prefix_ids[res["prefix"]])
            elif "pool" in res:
                # Reference to a prefix pool — look up by name
                pool_query = f"""
                query {{
                    CoreIPPrefixPool(name__value: "{res["pool"]}") {{
                        edges {{ node {{ id }} }}
                    }}
                }}
                """
                result = graphql(client, base_url, pool_query)
                edges = result.get("CoreIPPrefixPool", {}).get("edges", [])
                if edges:
                    resource_ids.append(edges[0]["node"]["id"])
                else:
                    print(f"  ⚠  Pool '{name}': referenced pool '{res['pool']}' not found")

        if not resource_ids:
            print(f"  ⚠  Pool '{name}': no valid resources, skipping")
            continue

        create_data: dict[str, Any] = {
            "name": {"value": name},
            "description": {"value": pool.get("description", "")},
            "default_prefix_length": {"value": pool.get("default_prefix_length", 32)},
            "resources": [{"id": rid} for rid in resource_ids],
        }

        pool_id = get_or_create(
            client,
            base_url,
            "CoreIPAddressPool",
            "name",
            name,
            create_data,
            label=f"IPAddressPool: {name}",
        )
        pool_ids[name] = pool_id
    return pool_ids


def populate_number_pools(
    client: httpx.Client,
    base_url: str,
    pool_defs: dict,
) -> dict[str, str]:
    """Create number pools. Returns {pool_name: pool_id} mapping."""
    pool_ids = {}
    for pool in pool_defs.get("number_pools", []):
        name = pool["name"]
        create_data: dict[str, Any] = {
            "name": {"value": name},
            "description": {"value": pool.get("description", "")},
            "start_range": {"value": pool["start_range"]},
            "end_range": {"value": pool["end_range"]},
        }

        pool_id = get_or_create(
            client,
            base_url,
            "CoreNumberPool",
            "name",
            name,
            create_data,
            label=f"NumberPool: {name}",
        )
        pool_ids[name] = pool_id
    return pool_ids


# ---------------------------------------------------------------------------
# IP prefix population (used by both static and pool flows)
# ---------------------------------------------------------------------------


def populate_ip_prefixes(
    client: httpx.Client,
    base_url: str,
    seed: dict,
    namespace_id: str,
) -> dict[str, str]:
    """Create IP prefixes (supernets). Returns {prefix: id} mapping."""
    prefix_ids = {}
    for pfx in seed.get("ip_prefixes", []):
        prefix = pfx["prefix"]
        pfx_id = get_or_create(
            client,
            base_url,
            "IpamPrefix",
            "prefix",
            prefix,
            {
                "prefix": {"value": prefix},
                "description": {"value": pfx.get("description", "")},
                "ip_namespace": {"id": namespace_id},
            },
            label=f"Prefix: {prefix}",
        )
        prefix_ids[prefix] = pfx_id
    return prefix_ids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Populate Infrahub with seed data")
    parser.add_argument(
        "--url",
        default=os.getenv("INFRAHUB_URL", "http://localhost:8000"),
        help="Infrahub server URL",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("INFRAHUB_TOKEN", ""),
        help="API token for authentication",
    )
    parser.add_argument(
        "--seed-file",
        default=None,
        help="Path to seed data YAML file (default: infrahub/data/seed_data.yml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse seed data without creating objects",
    )
    parser.add_argument(
        "--with-pools",
        action="store_true",
        help="Create resource pools (IP prefix, IP address, number pools) from pool_definitions.yml",
    )
    parser.add_argument(
        "--pool-file",
        default=None,
        help="Path to pool definitions YAML file (default: data/pool_definitions.yml)",
    )
    args = parser.parse_args()

    project_root = get_project_root()

    # Load seed data
    seed_file = (
        Path(args.seed_file)
        if args.seed_file
        else project_root / "backend" / "network_synapse" / "data" / "seed_data.yml"
    )
    if not seed_file.exists():
        print(f"❌ Seed file not found: {seed_file}")
        sys.exit(1)

    with seed_file.open() as f:
        seed = yaml.safe_load(f)

    # Load pool definitions if --with-pools is set
    pool_defs = None
    if args.with_pools:
        pool_file = (
            Path(args.pool_file)
            if args.pool_file
            else project_root / "backend" / "network_synapse" / "data" / "pool_definitions.yml"
        )
        if not pool_file.exists():
            print(f"❌ Pool definitions file not found: {pool_file}")
            sys.exit(1)
        with pool_file.open() as f:
            pool_defs = yaml.safe_load(f)

    print(f"🔧 Project root: {project_root}")
    print(f"🌐 Infrahub URL: {args.url}")
    print(f"📄 Seed file: {seed_file}")
    print(
        f"📦 Seed data loaded: {len(seed.get('devices', []))} devices, "
        f"{len(seed.get('interfaces', []))} interfaces, "
        f"{len(seed.get('bgp_sessions', []))} BGP sessions"
    )
    if pool_defs:
        print(
            f"🏊 Pool definitions loaded: "
            f"{len(pool_defs.get('ip_prefix_pools', []))} prefix pools, "
            f"{len(pool_defs.get('ip_address_pools', []))} address pools, "
            f"{len(pool_defs.get('number_pools', []))} number pools"
        )

    if args.dry_run:
        print("\n🏁 Dry run complete. Seed data parsed successfully.")
        return

    # Build headers — authenticate if no token provided
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-INFRAHUB-KEY"] = args.token
    else:
        # Auto-login with default credentials
        print("\n🔑 No token provided, attempting auto-login...")
        try:
            login_resp = httpx.post(
                f"{args.url}/api/auth/login",
                json={"username": "admin", "password": "infrahub"},
                timeout=10.0,
            )
            login_data = login_resp.json()
            if "access_token" in login_data:
                headers["Authorization"] = f"Bearer {login_data['access_token']}"
                print("  ✅ Authenticated as admin")
            else:
                print(f"  ⚠  Login response: {login_data}")
        except Exception as e:
            print(f"  ⚠  Auto-login failed: {e} — continuing without auth")

    with httpx.Client(headers=headers) as client:
        print("\n" + "=" * 60)
        print("1️⃣  Creating manufacturer...")
        manufacturer_id = populate_manufacturer(client, args.url, seed)

        print("\n2️⃣  Creating location...")
        location_id = populate_location(client, args.url, seed)

        print("\n3️⃣  Creating platform...")
        platform_id = populate_platform(client, args.url, seed, manufacturer_id)

        print("\n4️⃣  Creating device types...")
        dt_ids = populate_device_types(client, args.url, seed, manufacturer_id, platform_id)

        print("\n5️⃣  Creating autonomous systems...")
        as_ids = populate_autonomous_systems(client, args.url, seed, manufacturer_id)

        print("\n6️⃣  Creating IP namespace...")
        namespace_id = populate_namespace(client, args.url)

        print("\n7️⃣  Creating VRFs...")
        vrf_ids = populate_vrfs(client, args.url, seed, namespace_id)

        print("\n8️⃣  Creating devices...")
        device_ids = populate_devices(
            client,
            args.url,
            seed,
            location_id,
            platform_id,
            dt_ids,
            as_ids,
        )

        print("\n9️⃣  Creating IP prefixes...")
        prefix_ids = populate_ip_prefixes(client, args.url, seed, namespace_id)

        # Resource pools (opt-in)
        if pool_defs:
            print("\n🏊  Creating IP prefix pools...")
            ip_prefix_pool_ids = populate_ip_prefix_pools(client, args.url, pool_defs, prefix_ids)

            print("\n🏊  Creating IP address pools...")
            ip_address_pool_ids = populate_ip_address_pools(client, args.url, pool_defs, prefix_ids)

            print("\n🏊  Creating number pools...")
            number_pool_ids = populate_number_pools(client, args.url, pool_defs)

        print("\n🔟  Creating IP addresses...")
        ip_ids = populate_ip_addresses(client, args.url, seed, namespace_id)

        print("\n1️⃣1️⃣  Creating interfaces...")
        iface_ids = populate_interfaces(
            client,
            args.url,
            seed,
            device_ids,
            ip_ids,
        )

        print("\n1️⃣2️⃣  Creating BGP sessions...")
        populate_bgp_sessions(
            client,
            args.url,
            seed,
            device_ids,
            as_ids,
            ip_ids,
            vrf_ids,
        )

    print("\n" + "=" * 60)
    print("🏁 Seed data population complete!")
    print(f"   Devices: {len(device_ids)}")
    print(f"   Interfaces: {len(iface_ids)}")
    print(f"   IP Addresses: {len(ip_ids)}")
    print(f"   Prefixes: {len(prefix_ids)}")
    print(f"   BGP Sessions: {len(seed.get('bgp_sessions', []))}")
    if pool_defs:
        print(f"   IP Prefix Pools: {len(ip_prefix_pool_ids)}")
        print(f"   IP Address Pools: {len(ip_address_pool_ids)}")
        print(f"   Number Pools: {len(number_pool_ids)}")


if __name__ == "__main__":
    main()
