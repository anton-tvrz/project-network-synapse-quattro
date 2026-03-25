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
    cmd = (
        "docker run --rm -it --privileged --network host "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "-v /var/run/netns:/var/run/netns "
        "-v /etc/hosts:/etc/hosts "
        "-v /var/lib/docker/containers:/var/lib/docker/containers "
        f"-v {PROJECT_ROOT}:{PROJECT_ROOT} -w {PROJECT_ROOT} "
        f"ghcr.io/srl-labs/clab:latest containerlab deploy --topo {PROJECT_ROOT}/containerlab/topology.clab.yml"
    )
    execute_command(ctx, cmd)


@task
def lab_destroy(ctx):
    """Destroy Containerlab topology."""
    cmd = (
        "docker run --rm -it --privileged --network host "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "-v /var/run/netns:/var/run/netns "
        "-v /etc/hosts:/etc/hosts "
        "-v /var/lib/docker/containers:/var/lib/docker/containers "
        f"-v {PROJECT_ROOT}:{PROJECT_ROOT} -w {PROJECT_ROOT} "
        f"ghcr.io/srl-labs/clab:latest containerlab destroy --topo {PROJECT_ROOT}/containerlab/topology.clab.yml"
    )
    execute_command(ctx, cmd)


@task
def lab_graph(ctx):
    """Serve an interactive topology graph of Containerlab."""
    cmd = (
        "docker run -d --rm --name clab-graph --privileged --network host "
        "-v /var/run/docker.sock:/var/run/docker.sock "
        "-v /var/run/netns:/var/run/netns "
        "-v /etc/hosts:/etc/hosts "
        "-v /var/lib/docker/containers:/var/lib/docker/containers "
        f"-v {PROJECT_ROOT}:{PROJECT_ROOT} -w {PROJECT_ROOT} "
        f"ghcr.io/srl-labs/clab:latest containerlab graph --topo {PROJECT_ROOT}/containerlab/topology.clab.yml"
    )
    print("Serving topology graph on http://localhost:50080")
    print("Run 'docker stop clab-graph' to stop the server.")
    execute_command(ctx, cmd)
