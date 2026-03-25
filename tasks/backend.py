"""Backend tasks — testing, config generation, schema management."""

from __future__ import annotations

from invoke import task

from .shared import execute_command


@task
def test_unit(ctx):
    """Run backend unit tests."""
    execute_command(
        ctx,
        "pytest tests/unit/ -v --cov=backend/network_synapse --cov-report=term-missing --cov-report=xml",
    )


@task
def test_integration(ctx):
    """Run backend integration tests (requires Infrahub/Temporal/Containerlab)."""
    execute_command(ctx, "pytest tests/integration/ -v --timeout=300")


@task
def test_all(ctx):
    """Run all tests (unit + integration)."""
    execute_command(
        ctx,
        "pytest tests/ -v "
        "--cov=backend/network_synapse --cov=workers/synapse_workers "
        "--cov-report=term-missing "
        "--cov-report=xml",
    )


@task
def generate_configs(ctx, device="all", url="", output_dir="", dry_run=False):
    """Generate SR Linux configurations from Infrahub data."""
    cmd = f"python -m network_synapse.scripts.generate_configs --device {device}"
    if url:
        cmd += f" --url {url}"
    if output_dir:
        cmd += f" --output-dir {output_dir}"
    if dry_run:
        cmd += " --dry-run"
    execute_command(ctx, cmd, warn=True)


@task
def load_schemas(ctx):
    """Load schemas into Infrahub via infrahubctl.

    Loads in 3 batches (base -> extensions -> project) to respect dependencies.
    Requires INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN env vars (set in .env).
    """
    batches = [
        (
            "base",
            [
                "library/schema-library/base/organization.yml",
                "library/schema-library/base/location.yml",
                "library/schema-library/base/ipam.yml",
                "library/schema-library/base/dcim.yml",
            ],
        ),
        (
            "extensions",
            [
                "library/schema-library/extensions/vrf/vrf.yml",
                "library/schema-library/extensions/routing/routing.yml",
                "library/schema-library/extensions/routing_bgp/bgp.yml",
            ],
        ),
        (
            "project",
            [
                "backend/network_synapse/schemas/network_device.yml",
                "backend/network_synapse/schemas/network_interface.yml",
            ],
        ),
    ]
    for name, files in batches:
        file_args = " ".join(files)
        print(f"\n📦 Loading {name} schemas...")
        execute_command(ctx, f"infrahubctl schema load {file_args}")


@task
def seed_data(ctx, url="http://localhost:8000"):
    """Seed data into Infrahub."""
    execute_command(ctx, f"python backend/network_synapse/data/populate_sot.py --url {url}")


@task
def typecheck(ctx):
    """Run mypy type checking on backend."""
    execute_command(ctx, "mypy backend/", warn=True)
