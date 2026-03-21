"""Query Infrahub and render Jinja2 templates to generate Nokia SR Linux configurations.

Usage:
    # Generate configs for all devices (requires running Infrahub)
    python -m network_synapse.scripts.generate_configs --device all

    # Generate for a single device, dry-run (print to stdout)
    python -m network_synapse.scripts.generate_configs --device spine01 --dry-run

    # Custom Infrahub URL and output directory
    python -m network_synapse.scripts.generate_configs --url http://infrahub:8000 --output-dir ./configs

Environment Variables:
    INFRAHUB_URL:   Infrahub server URL (default: http://localhost:8000)
    INFRAHUB_TOKEN: API token for authentication
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader

from network_synapse.infrahub.client import DeviceNotFoundError, InfrahubConfigClient

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
DEFAULT_OUTPUT_DIR = Path.cwd() / "generated-configs"


# ---------------------------------------------------------------------------
# Template rendering (original functions — preserved for backward compat)
# ---------------------------------------------------------------------------


def get_jinja_env() -> Environment:
    """Create Jinja2 environment pointing at the templates directory."""
    return Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


def generate_bgp_config(device_data: dict) -> str:
    """Render SR Linux BGP JSON config from device data dict."""
    env = get_jinja_env()
    template = env.get_template("srlinux_bgp.j2")
    return template.render(**device_data)


def generate_interface_config(device_data: dict) -> str:
    """Render SR Linux interface JSON config from device data dict."""
    env = get_jinja_env()
    template = env.get_template("srlinux_interfaces.j2")
    return template.render(**device_data)


# ---------------------------------------------------------------------------
# JSON validation
# ---------------------------------------------------------------------------


def validate_json_output(rendered: str, label: str) -> str:
    """Parse rendered template output as JSON to validate, then re-format with indent.

    Returns pretty-printed JSON on success, or original string with a warning on failure.
    """
    try:
        parsed = json.loads(rendered)
        return json.dumps(parsed, indent=2)
    except json.JSONDecodeError as exc:
        print(f"WARNING: {label} output is not valid JSON: {exc}", file=sys.stderr)
        return rendered


# ---------------------------------------------------------------------------
# Per-device generation
# ---------------------------------------------------------------------------


def generate_for_device_via_transforms(
    client: InfrahubConfigClient,
    hostname: str,
    output_dir: Path,
    dry_run: bool,
) -> bool:
    """Generate SR Linux configs using Infrahub server-side transforms.

    Returns True on success, False on failure.
    """
    print(f"\n{'=' * 50}")
    print(f"  Generating configs for: {hostname} (via transforms)")
    print(f"{'=' * 50}")

    try:
        bgp_json = validate_json_output(
            client.execute_transform("srlinux_bgp_config", {"hostname": hostname}),
            f"{hostname}/bgp",
        )
        iface_json = validate_json_output(
            client.execute_transform("srlinux_interface_config", {"hostname": hostname}),
            f"{hostname}/interfaces",
        )
    except Exception as exc:
        print(f"  ERROR: Transform execution failed for '{hostname}': {exc}", file=sys.stderr)
        return False

    if dry_run:
        print(f"\n--- {hostname}/bgp.json ---")
        print(bgp_json)
        print(f"\n--- {hostname}/interfaces.json ---")
        print(iface_json)
        return True

    device_dir = output_dir / hostname
    device_dir.mkdir(parents=True, exist_ok=True)

    bgp_path = device_dir / "bgp.json"
    iface_path = device_dir / "interfaces.json"

    bgp_path.write_text(bgp_json + "\n")
    iface_path.write_text(iface_json + "\n")

    print(f"  Written: {bgp_path}")
    print(f"  Written: {iface_path}")

    return True


def generate_for_device(
    client: InfrahubConfigClient,
    hostname: str,
    output_dir: Path,
    dry_run: bool,
) -> bool:
    """Generate all SR Linux configs for a single device.

    Returns True on success, False on failure.
    """
    print(f"\n{'=' * 50}")
    print(f"  Generating configs for: {hostname}")
    print(f"{'=' * 50}")

    try:
        device_config = client.get_device_config(hostname)
    except DeviceNotFoundError:
        print(f"  ERROR: Device '{hostname}' not found in Infrahub", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  ERROR: Failed to query Infrahub for '{hostname}': {exc}", file=sys.stderr)
        return False

    # Transform to template variables
    bgp_vars = device_config.to_bgp_template_vars()
    iface_vars = device_config.to_interface_template_vars()

    # Render templates
    bgp_json = validate_json_output(
        generate_bgp_config(bgp_vars.model_dump()),
        f"{hostname}/bgp",
    )
    iface_json = validate_json_output(
        generate_interface_config(iface_vars.model_dump()),
        f"{hostname}/interfaces",
    )

    if dry_run:
        print(f"\n--- {hostname}/bgp.json ---")
        print(bgp_json)
        print(f"\n--- {hostname}/interfaces.json ---")
        print(iface_json)
        return True

    # Write output files
    device_dir = output_dir / hostname
    device_dir.mkdir(parents=True, exist_ok=True)

    bgp_path = device_dir / "bgp.json"
    iface_path = device_dir / "interfaces.json"

    bgp_path.write_text(bgp_json + "\n")
    iface_path.write_text(iface_json + "\n")

    print(f"  Written: {bgp_path}")
    print(f"  Written: {iface_path}")

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entrypoint for config generation."""
    parser = argparse.ArgumentParser(
        description="Generate SR Linux JSON configs from Infrahub source of truth",
    )
    parser.add_argument(
        "--device",
        default="all",
        help="Device hostname or 'all' (default: all)",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("INFRAHUB_URL", "http://localhost:8000"),
        help="Infrahub server URL (default: $INFRAHUB_URL or http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("INFRAHUB_TOKEN", ""),
        help="Infrahub API token (default: $INFRAHUB_TOKEN or auto-login)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for generated configs (default: ./generated-configs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print configs to stdout instead of writing files",
    )
    parser.add_argument(
        "--use-transforms",
        action="store_true",
        help="Use Infrahub server-side transforms instead of local Jinja2 templates",
    )
    args = parser.parse_args()

    print(f"Infrahub URL: {args.url}")
    print(f"Output dir:   {args.output_dir}")
    print(f"Dry run:      {args.dry_run}")
    if args.use_transforms:
        print("Mode:         Infrahub transforms (server-side)")

    try:
        with InfrahubConfigClient(url=args.url, token=args.token) as client:
            # Resolve device list
            if args.device == "all":
                hostnames = client.get_all_device_hostnames()
                print(f"Found {len(hostnames)} devices: {', '.join(hostnames)}")
            else:
                hostnames = [args.device]

            # Generate configs for each device
            gen_func = generate_for_device_via_transforms if args.use_transforms else generate_for_device
            results: dict[str, bool] = {}
            for hostname in hostnames:
                results[hostname] = gen_func(
                    client,
                    hostname,
                    args.output_dir,
                    args.dry_run,
                )

    except httpx.ConnectError:
        print(f"\nERROR: Cannot connect to Infrahub at {args.url}", file=sys.stderr)
        print("Is Infrahub running? Check INFRAHUB_URL environment variable.", file=sys.stderr)
        sys.exit(1)

    # Summary
    print(f"\n{'=' * 50}")
    print("  Config Generation Summary")
    print(f"{'=' * 50}")
    for hostname, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {hostname}: {status}")

    failed = [h for h, ok in results.items() if not ok]
    if failed:
        print(f"\n{len(failed)} device(s) failed.", file=sys.stderr)
        sys.exit(1)

    print(f"\nAll {len(results)} device(s) generated successfully.")


if __name__ == "__main__":
    main()
