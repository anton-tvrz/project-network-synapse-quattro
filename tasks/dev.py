"""Development infrastructure tasks — Docker, Containerlab."""

from __future__ import annotations

from invoke import task

from .shared import PROJECT_ROOT, execute_command


@task
def build(ctx):
    """Build Docker images for development."""
    execute_command(ctx, f"docker build -f {PROJECT_ROOT}/development/Dockerfile -t synapse-worker .")


@task
def start(ctx):
    """Start full development environment (Docker Compose)."""
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose.yml up -d")


@task
def stop(ctx):
    """Stop development environment."""
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose.yml down")


@task
def deps(ctx):
    """Start infrastructure dependencies only (Infrahub, Temporal, Neo4j, Redis)."""
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose-deps.yml up -d")


@task
def deps_stop(ctx):
    """Stop infrastructure dependencies."""
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose-deps.yml down")


@task
def lab_deploy(ctx):
    """Deploy Containerlab topology."""
    execute_command(ctx, f"sudo containerlab deploy --topo {PROJECT_ROOT}/containerlab/topology.clab.yml")


@task
def lab_destroy(ctx):
    """Destroy Containerlab topology."""
    execute_command(ctx, f"sudo containerlab destroy --topo {PROJECT_ROOT}/containerlab/topology.clab.yml")
