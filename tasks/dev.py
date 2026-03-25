"""Development infrastructure tasks — Docker, Containerlab."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from invoke import task

if TYPE_CHECKING:
    from invoke.context import Context

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
def lab_deploy(ctx: Context) -> None:
    """Deploy Containerlab topology."""
    quoted_root = shlex.quote(str(PROJECT_ROOT))
    cmd = (
        "docker run --rm -it --privileged --network host "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "-v /var/run/netns:/var/run/netns "
        "-v /etc/hosts:/etc/hosts "
        "-v /var/lib/docker/containers:/var/lib/docker/containers "
        f"-v {quoted_root}:{quoted_root} -w {quoted_root} "
        "ghcr.io/srl-labs/clab:latest containerlab deploy "
        f"--topo {quoted_root}/containerlab/topology.clab.yml"
    )
    execute_command(ctx, cmd)


@task
def lab_destroy(ctx: Context) -> None:
    """Destroy Containerlab topology."""
    quoted_root = shlex.quote(str(PROJECT_ROOT))
    cmd = (
        "docker run --rm -it --privileged --network host "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "-v /var/run/netns:/var/run/netns "
        "-v /etc/hosts:/etc/hosts "
        "-v /var/lib/docker/containers:/var/lib/docker/containers "
        f"-v {quoted_root}:{quoted_root} -w {quoted_root} "
        "ghcr.io/srl-labs/clab:latest containerlab destroy "
        f"--topo {quoted_root}/containerlab/topology.clab.yml"
    )
    execute_command(ctx, cmd)


@task
def lab_graph(ctx: Context) -> None:
    """Serve an interactive topology graph of Containerlab."""
    execute_command(ctx, "docker rm -f clab-graph >/dev/null 2>&1 || true")
    quoted_root = shlex.quote(str(PROJECT_ROOT))
    cmd = (
        "docker run -d --rm --name clab-graph --privileged --network host "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "-v /var/run/netns:/var/run/netns "
        "-v /etc/hosts:/etc/hosts "
        "-v /var/lib/docker/containers:/var/lib/docker/containers "
        f"-v {quoted_root}:{quoted_root} -w {quoted_root} "
        "ghcr.io/srl-labs/clab:latest containerlab graph "
        f"--topo {quoted_root}/containerlab/topology.clab.yml"
    )
    execute_command(ctx, cmd)
    print("Serving topology graph on http://localhost:50080")
    print("Run 'docker stop clab-graph' to stop the server.")
