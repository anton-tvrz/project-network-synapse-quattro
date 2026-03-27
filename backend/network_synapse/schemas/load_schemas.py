#!/usr/bin/env python3
"""
Load Infrahub schemas for the Synapse network automation project.

This script loads schemas into Infrahub in the correct dependency order:
  1. VRF extension       -> IpamVRF, IpamRouteTarget
  2. Routing base        -> RoutingProtocol (generic)
  3. Routing BGP         -> RoutingAutonomousSystem, RoutingBGPPeerGroup, RoutingBGPSession
  4. Network Device ext  -> DcimDevice custom attributes (management_ip, lab_node_name, asn)
  5. Network Interface   -> InterfacePhysical custom attributes (role)

Usage:
    python load_schemas.py [--url http://localhost:8000] [--token <api-token>]

Environment Variables:
    INFRAHUB_URL:   Infrahub server URL (default: http://localhost:8000)
    INFRAHUB_TOKEN: API token for authentication (optional for local dev)
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)


# Schema files to load in order (paths relative to project root)
# Schema load batches — files in same batch are loaded in a single API call
# to resolve circular dependencies within the batch.
SCHEMA_LOAD_BATCHES = [
    # Batch 1: All base schemas (have circular refs between org <-> dcim)
    [
        "library/schema-library/base/organization.yml",
        "library/schema-library/base/location.yml",
        "library/schema-library/base/ipam.yml",
        "library/schema-library/base/dcim.yml",
    ],
    # Batch 2: Extensions (depend on base schemas)
    [
        "library/schema-library/extensions/vrf/vrf.yml",
        "library/schema-library/extensions/routing/routing.yml",
        "library/schema-library/extensions/routing_bgp/bgp.yml",
    ],
    # Batch 3: Project-specific schemas (depend on base + extensions)
    [
        "backend/network_synapse/schemas/network_device.yml",
        "backend/network_synapse/schemas/network_interface.yml",
    ],
]

# Flat list for backward compatibility
SCHEMA_LOAD_ORDER = [f for batch in SCHEMA_LOAD_BATCHES for f in batch]


def get_project_root() -> Path:
    """Find the project root directory."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    # Fallback: assume script is at infrahub/schemas/load_schemas.py
    return current.parent.parent.parent


def load_yaml_file(filepath: Path) -> dict:
    """Load and parse a YAML file."""
    with filepath.open() as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    return data


def load_schema_into_infrahub(
    client: "httpx.Client",
    base_url: str,
    schema_data: dict,
    schema_name: str,
) -> bool:
    """Load a single schema file into Infrahub via the API."""
    # Infrahub schema load endpoint
    url = f"{base_url}/api/schema/load"

    # Filter out comment-only schemas (like bgp_session.yml which is documentation only)
    has_nodes = "nodes" in schema_data and schema_data["nodes"]
    has_generics = "generics" in schema_data and schema_data["generics"]
    has_extensions = "extensions" in schema_data and schema_data["extensions"]

    if not (has_nodes or has_generics or has_extensions):
        print(f"  ⏭  {schema_name}: No nodes/generics/extensions to load, skipping")
        return True

    payload = {"schemas": [schema_data]}

    try:
        response = client.post(url, json=payload, timeout=30.0)

        if response.status_code == 200:
            result = response.json()
            if result.get("errors"):
                print(f"  ⚠  {schema_name}: Loaded with warnings:")
                for err in result["errors"]:
                    print(f"     {err.get('message', err)}")
            else:
                print(f"  ✅ {schema_name}: Loaded successfully")
            return True
        if response.status_code == 422:
            # Schema validation error
            error_detail = response.json()
            print(f"  ❌ {schema_name}: Schema validation error (422):")
            print(f"     {json.dumps(error_detail, indent=2)}")
            return False
        print(f"  ❌ {schema_name}: HTTP {response.status_code}")
        print(f"     {response.text[:500]}")
        return False

    except httpx.RequestError as e:
        print(f"  ❌ {schema_name}: Connection error: {e}")
        return False


def verify_schema_loaded(client: "httpx.Client", base_url: str) -> None:
    """Verify loaded schemas by listing all node types."""
    url = f"{base_url}/api/schema/summary"
    try:
        response = client.get(url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            nodes = data.get("nodes", {})
            generics = data.get("generics", {})

            # Look for our expected nodes
            routing_nodes = [n for n in nodes if "Routing" in n or "Ipam" in n]
            dcim_nodes = [n for n in nodes if "Dcim" in n]
            interface_nodes = [n for n in nodes if "Interface" in n]

            print("\n📋 Schema verification:")
            print(f"   Total nodes: {len(nodes)}")
            print(f"   Total generics: {len(generics)}")
            print(f"\n   Routing/IPAM nodes: {', '.join(sorted(routing_nodes))}")
            print(f"   DCIM nodes: {', '.join(sorted(dcim_nodes))}")
            print(f"   Interface nodes: {', '.join(sorted(interface_nodes))}")

            # Check for expected nodes
            expected = [
                "IpamVRF",
                "RoutingAutonomousSystem",
                "RoutingBGPPeerGroup",
                "RoutingBGPSession",
            ]
            missing = [n for n in expected if n not in nodes]
            if missing:
                print(f"\n   ⚠  Missing expected nodes: {', '.join(missing)}")
            else:
                print("\n   ✅ All expected BGP/Routing nodes present")

    except Exception as e:
        print(f"\n⚠  Could not verify schemas: {e}")


# ruff: noqa: PLR0912
def main():
    parser = argparse.ArgumentParser(description="Load Infrahub schemas for Synapse project")
    parser.add_argument(
        "--url",
        default=os.getenv("INFRAHUB_URL", "http://localhost:8000"),
        help="Infrahub server URL (default: $INFRAHUB_URL or http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("INFRAHUB_TOKEN", ""),
        help="API token for authentication (default: $INFRAHUB_TOKEN)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate schemas without loading",
    )
    args = parser.parse_args()

    project_root = get_project_root()
    print(f"🔧 Project root: {project_root}")
    print(f"🌐 Infrahub URL: {args.url}")
    print(f"📦 Loading {len(SCHEMA_LOAD_ORDER)} schema files...\n")

    # Build headers
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-INFRAHUB-KEY"] = args.token

    # Parse all schema files first
    schemas = []
    for schema_path in SCHEMA_LOAD_ORDER:
        filepath = project_root / schema_path
        if not filepath.exists():
            print(f"  ❌ File not found: {filepath}")
            sys.exit(1)

        schema_data = load_yaml_file(filepath)
        schemas.append((schema_path, schema_data))
        print(f"  📄 Parsed: {schema_path}")

    if args.dry_run:
        print("\n🏁 Dry run complete. All schema files parsed successfully.")
        return

    # Load schemas into Infrahub in batches
    print(f"\n🚀 Loading schemas into Infrahub at {args.url}...\n")
    batch_success = 0
    batch_fail = 0

    with httpx.Client(headers=headers) as client:
        for batch_idx, batch_files in enumerate(SCHEMA_LOAD_BATCHES, 1):
            batch_schemas = []
            batch_names = []
            for schema_path in batch_files:
                filepath = project_root / schema_path
                schema_data = load_yaml_file(filepath)
                # Only include schemas with actual content
                has_nodes = "nodes" in schema_data and schema_data["nodes"]
                has_generics = "generics" in schema_data and schema_data["generics"]
                has_extensions = "extensions" in schema_data and schema_data["extensions"]
                if has_nodes or has_generics or has_extensions:
                    batch_schemas.append(schema_data)
                    batch_names.append(Path(schema_path).stem)

            if not batch_schemas:
                print(f"  ⏭  Batch {batch_idx}: No schemas to load, skipping")
                continue

            print(f"  📦 Batch {batch_idx}: Loading {', '.join(batch_names)}...")
            url = f"{args.url}/api/schema/load"
            payload = {"schemas": batch_schemas}

            try:
                response = client.post(url, json=payload, timeout=180.0)
                if response.status_code == 200:
                    result = response.json()
                    if result.get("errors"):
                        print(f"  ⚠  Batch {batch_idx}: Loaded with warnings:")
                        for err in result["errors"]:
                            print(f"     {err.get('message', err)}")
                    else:
                        print(f"  ✅ Batch {batch_idx}: All schemas loaded successfully")
                    batch_success += 1
                else:
                    print(f"  ❌ Batch {batch_idx}: HTTP {response.status_code}")
                    try:
                        error_detail = response.json()
                        print(f"     {json.dumps(error_detail, indent=2)}")
                    except ValueError:
                        print(f"     {response.text[:500]}")
                    batch_fail += 1
                    print(f"\n🛑 Stopping due to failure in batch {batch_idx}")
                    break
            except httpx.RequestError as e:
                print(f"  ❌ Batch {batch_idx}: Connection error: {e}")
                batch_fail += 1
                break

        # Verify
        if batch_fail == 0:
            verify_schema_loaded(client, args.url)

    print(f"\n🏁 Done: {batch_success} batches loaded, {batch_fail} failed")
    sys.exit(1 if batch_fail > 0 else 0)


if __name__ == "__main__":
    main()
