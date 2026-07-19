"""Development infrastructure tasks — Docker, Containerlab."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from invoke import task

if TYPE_CHECKING:
    from invoke.context import Context

from .shared import PROJECT_ROOT, execute_command

# ---------------------------------------------------------------------------
# Containerlab helpers
# ---------------------------------------------------------------------------

_CLAB_IMAGE = "ghcr.io/srl-labs/clab:latest"


def _clab_docker_cmd(
    quoted_root: str, clab_args: str, *, docker_flags: str = "--rm -it --privileged --pid host"
) -> str:
    """Build a Docker command for running Containerlab inside a container.

    Centralises the common volume mounts required for Docker-outside-of-Docker
    Containerlab execution. ``--pid host`` is required on OrbStack: without it
    containerlab cannot resolve the started nodes' network-namespace paths
    ("namespace path not available") and every deploy fails after creating
    the containers.
    """
    return (
        f"docker run {docker_flags} --network host "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "-v /var/run/netns:/var/run/netns "
        "-v /etc/hosts:/etc/hosts "
        "-v /var/lib/docker/containers:/var/lib/docker/containers "
        f"-v {quoted_root}:{quoted_root} -w {quoted_root} "
        f"{_CLAB_IMAGE} {clab_args}"
    )


# ---------------------------------------------------------------------------
# Docker tasks
# ---------------------------------------------------------------------------


@task
def build(ctx: Context) -> None:
    """Build Docker images for development."""
    execute_command(ctx, f"docker build -f {PROJECT_ROOT}/development/Dockerfile -t synapse-worker .")


@task
def start(ctx: Context) -> None:
    """Start full development environment (Docker Compose)."""
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose.yml up -d")


@task
def stop(ctx: Context) -> None:
    """Stop development environment."""
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose.yml down")


@task
def deps(ctx: Context) -> None:
    """Start infrastructure dependencies only (Infrahub, Temporal, Neo4j, Redis)."""
    # The collector services (suzieq, gnmic) join the containerlab management
    # bridge, declared external in the compose file. Pre-create it when the
    # lab hasn't been deployed yet — containerlab reuses an existing network
    # with a matching name, so lab-first and deps-first both work.
    execute_command(
        ctx,
        "docker network inspect clab >/dev/null 2>&1 || "
        "docker network create --driver bridge --subnet 172.20.20.0/24 --gateway 172.20.20.1 clab",
    )
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose-deps.yml up -d")


@task
def deps_stop(ctx: Context) -> None:
    """Stop infrastructure dependencies."""
    execute_command(ctx, f"docker compose -f {PROJECT_ROOT}/development/docker-compose-deps.yml down")


# ---------------------------------------------------------------------------
# Containerlab tasks
# ---------------------------------------------------------------------------


@task
def lab_deploy(ctx: Context) -> None:
    """Deploy Containerlab topology."""
    quoted_root = shlex.quote(str(PROJECT_ROOT))
    topo = f"{quoted_root}/containerlab/topology.clab.yml"
    execute_command(ctx, _clab_docker_cmd(quoted_root, f"containerlab deploy --topo {topo}"))


@task
def lab_destroy(ctx: Context) -> None:
    """Destroy Containerlab topology."""
    quoted_root = shlex.quote(str(PROJECT_ROOT))
    topo = f"{quoted_root}/containerlab/topology.clab.yml"
    execute_command(ctx, _clab_docker_cmd(quoted_root, f"containerlab destroy --topo {topo}"))


@task
def lab_syslog(ctx: Context) -> None:
    """Point fabric syslog at the Loki/Alloy collector pipeline (Issue #169)."""
    execute_command(ctx, "uv run python -m network_synapse.scripts.configure_syslog")


@task
def lab_graph(ctx: Context) -> None:
    """Serve an interactive topology graph of Containerlab."""
    execute_command(ctx, "docker rm -f clab-graph >/dev/null 2>&1 || true")
    quoted_root = shlex.quote(str(PROJECT_ROOT))
    topo = f"{quoted_root}/containerlab/topology.clab.yml"
    execute_command(
        ctx,
        _clab_docker_cmd(
            quoted_root,
            f"containerlab graph --topo {topo}",
            docker_flags="-d --rm --name clab-graph --privileged --pid host",
        ),
    )
    print("Serving topology graph on http://localhost:50080")
    print("Run 'docker stop clab-graph' to stop the server.")
