"""Demo tasks — one-command bring-up, readiness gate, and reset (Issue #189).

Before this, a demo took seven manual steps across three documents with no
readiness signal anywhere. `dev.deps` returns as soon as Docker has *started*
the containers, but Infrahub needs 60-90s beyond that before it accepts a
schema load — so `backend.load-schemas` raced a cold Infrahub, and lost often
enough to be the most likely way a demo dies in its first two minutes.

  demo.up      start everything, gated on readiness, in dependency order
  demo.status  one-shot go/no-go check, non-zero exit if anything is down
  demo.reset   return to a clean pre-demo state (destructive)

The host processes (worker, portal, drift exporter) stay separate: they run
in the foreground and belong in their own terminals. `demo.up` prints them as
next steps rather than backgrounding processes it cannot supervise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from invoke import Exit, task

from network_synapse.readiness import (
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    ProbeResult,
    all_ready,
    demo_probes,
    format_summary,
    run_probe,
    wait_until_ready,
)

if TYPE_CHECKING:
    from invoke.context import Context

from .shared import PROJECT_ROOT, execute_command

DEPS_COMPOSE = f"{PROJECT_ROOT}/development/docker-compose-deps.yml"

NEXT_STEPS = """
Stack is up. Start the host processes, each in its own terminal:

  uv run invoke workers.start              Temporal worker
  uv run invoke presentation.start         Self-service portal
  uv run invoke collector.suzieq-exporter  Drift scores -> Prometheus

Surfaces:

  Infrahub            http://localhost:8000
  Temporal UI         http://localhost:8080
  Presentation portal http://localhost:8081
  Grafana             http://localhost:3000   (admin/admin)
  Prometheus          http://localhost:9090
"""


def check_now() -> list[ProbeResult]:
    """Probe every demo service once."""
    return [run_probe(probe) for probe in demo_probes()]


def _docker_available(ctx: Context) -> bool:
    """True if a Docker daemon is reachable."""
    result = ctx.run("docker info", hide=True, warn=True)
    return bool(result and result.ok)


def _confirm(prompt: str) -> bool:
    """Ask the operator to confirm a destructive action."""
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}


def _report(results: list[ProbeResult]) -> None:
    print(format_summary(results))


@task(
    help={
        "skip-lab": "Don't deploy the Containerlab topology.",
        "timeout": f"Seconds to wait for the stack to become ready (default {DEFAULT_TIMEOUT_SECONDS}).",
    }
)
def up(ctx: Context, skip_lab: bool = False, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    """Start the full demo stack, waiting for each layer before using it."""
    if not _docker_available(ctx):
        # Fail here with the actual cause. Otherwise the first compose command
        # fails with a socket path nobody reads as "OrbStack isn't running".
        raise Exit("Docker is not reachable. Start OrbStack (or Docker Desktop) and retry.", code=1)

    print("==> Starting infrastructure dependencies")
    execute_command(
        ctx,
        "docker network inspect clab >/dev/null 2>&1 || "
        "docker network create --driver bridge --subnet 172.20.20.0/24 --gateway 172.20.20.1 clab",
    )
    execute_command(ctx, f"docker compose -f {DEPS_COMPOSE} up -d")

    print(f"==> Waiting for the stack to become ready (up to {timeout}s; Infrahub takes 60-90s)")
    results = wait_until_ready(
        demo_probes(),
        timeout=timeout,
        interval=DEFAULT_INTERVAL_SECONDS,
    )
    _report(results)
    if not all_ready(results):
        # Abort rather than proceed: a schema load against a cold Infrahub
        # fails with an error that says nothing about the real cause.
        raise Exit("Stack did not become ready; not loading schemas. See the hints above.", code=1)

    print("==> Loading schemas")
    execute_command(ctx, "uv run invoke backend.load-schemas")
    print("==> Seeding data")
    execute_command(ctx, "uv run invoke backend.seed-data")

    if not skip_lab:
        print("==> Deploying the Containerlab topology")
        execute_command(ctx, "uv run invoke dev.lab-deploy")

    print(NEXT_STEPS)


@task
def status(ctx: Context) -> None:
    """Check whether the demo stack is ready. Non-zero exit if it isn't."""
    results = check_now()
    _report(results)
    if not all_ready(results):
        raise Exit(code=1)
    print("\nAll services ready.")


@task(help={"yes": "Skip the confirmation prompt."})
def reset(ctx: Context, yes: bool = False) -> None:
    """Destroy the lab and wipe all stack state, for a clean re-run.

    Destructive: removes the Docker volumes holding Infrahub's graph, Temporal
    history, Prometheus/InfluxDB series, and SuzieQ parquet. Re-seeding on top
    of prior state is not the same as starting clean, which is why this exists
    as a distinct operation rather than "just run seed-data again".
    """
    if not yes and not _confirm("Destroy the lab and delete ALL stack data (Infrahub, Temporal, metrics)?"):
        raise Exit("Aborted; nothing was changed.", code=1)

    print("==> Destroying the Containerlab topology")
    execute_command(ctx, "uv run invoke dev.lab-destroy", warn=True)
    print("==> Removing containers and volumes")
    execute_command(ctx, f"docker compose -f {DEPS_COMPOSE} down -v")
    print("\nClean. Run `uv run invoke demo.up` to rebuild the demo environment.")
