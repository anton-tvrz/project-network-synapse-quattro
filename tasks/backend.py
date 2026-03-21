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
def load_schemas(ctx, url="http://localhost:8000"):
    """Load schemas into Infrahub."""
    execute_command(ctx, f"python backend/network_synapse/schemas/load_schemas.py --url {url}")


@task
def seed_data(ctx, url="http://localhost:8000"):
    """Seed data into Infrahub."""
    execute_command(ctx, f"python backend/network_synapse/data/populate_sot.py --url {url}")


@task
def typecheck(ctx):
    """Run mypy type checking on backend."""
    execute_command(ctx, "mypy backend/", warn=True)
