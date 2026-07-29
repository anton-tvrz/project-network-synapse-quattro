"""Infrastructure readiness probing for demo/dev bring-up (Issue #189).

``invoke dev.deps`` returns as soon as Docker has *started* the containers,
but Infrahub needs 60-90s beyond that before it will serve schema writes
(Neo4j and the task-manager must come up first). Nothing gated on this, so
``backend.load-schemas`` raced a cold Infrahub — the most likely way a demo
dies in its first two minutes.

This module answers one question — "is the stack actually usable yet?" — and
answers it the same way for a blocking wait (``demo.up``) and a one-shot
check (``demo.status``).

Design notes:

  - A service being down is an expected state, not an exception. Probes
    return ``(ready, detail)``; only programming errors raise.
  - Infrahub is probed over HTTP against ``/api/schema/summary``, not by a
    TCP connect to 8000. The port opens well before the schema API stops
    returning 500s, and it is the schema API that the next step needs.
  - Clock and probe-runner are injectable so the polling logic is testable
    without real waiting.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_INTERVAL_SECONDS = 5
PROBE_TIMEOUT_SECONDS = 5.0


class Clock(Protocol):
    """Injectable time source, so timeout logic is testable without waiting."""

    def now(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class _RealClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class Probe:
    """One service readiness check, plus what to tell the operator if it fails."""

    name: str
    kind: Literal["http", "tcp"]
    target: str
    hint: str


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single probe attempt."""

    probe: Probe
    ready: bool
    detail: str


def probe_tcp(host: str, port: int, timeout: float = PROBE_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """True if a TCP connection to host:port succeeds within ``timeout``."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as exc:
        return False, str(exc)


def probe_http(url: str, timeout: float = PROBE_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """True if ``url`` answers with a non-error status within ``timeout``.

    A warming-up Infrahub answers 500 on the schema API, so status matters —
    a bare "did it connect" check would report ready too early.
    """
    try:
        response = httpx.get(url, timeout=timeout)
    except Exception as exc:  # httpx raises a family of connect/read errors
        return False, str(exc)
    if response.status_code >= 400:
        return False, f"HTTP {response.status_code}"
    return True, ""


def run_probe(probe: Probe, timeout: float = PROBE_TIMEOUT_SECONDS) -> ProbeResult:
    """Execute one probe according to its kind."""
    if probe.kind == "http":
        ready, detail = probe_http(probe.target, timeout)
    else:
        host, _, port = probe.target.rpartition(":")
        ready, detail = probe_tcp(host, int(port), timeout)
    return ProbeResult(probe=probe, ready=ready, detail=detail)


def wait_until_ready(
    probes: list[Probe],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    clock: Clock | None = None,
    run: Callable[[Probe, float], ProbeResult] = run_probe,
    on_attempt: Callable[[list[ProbeResult]], None] | None = None,
) -> list[ProbeResult]:
    """Poll until every probe reports ready, or ``timeout`` elapses.

    Returns the final results in probe order — a timeout is reported, not
    raised, so the caller can print *which* service is down and what to do
    about it. Services that have answered are not probed again.
    """
    clock = clock or _RealClock()
    deadline = clock.now() + timeout
    settled: dict[str, ProbeResult] = {}

    while True:
        for probe in probes:
            if probe.name not in settled or not settled[probe.name].ready:
                settled[probe.name] = run(probe, PROBE_TIMEOUT_SECONDS)

        results = [settled[probe.name] for probe in probes]
        if on_attempt is not None:
            on_attempt(results)
        if all_ready(results) or clock.now() >= deadline:
            return results
        clock.sleep(interval)


def all_ready(results: list[ProbeResult]) -> bool:
    """True when every probe reported ready (vacuously true for none)."""
    return all(result.ready for result in results)


def format_summary(results: list[ProbeResult]) -> str:
    """Render a human-readable status table, with hints for what is down."""
    if not results:
        return "no services probed"
    width = max(len(result.probe.name) for result in results)
    lines = []
    for result in results:
        mark = "ok  " if result.ready else "DOWN"
        line = f"  {mark}  {result.probe.name.ljust(width)}  {result.probe.target}"
        if not result.ready:
            line += f"\n        {result.detail}\n        fix: {result.probe.hint}"
        lines.append(line)
    return "\n".join(lines)


def demo_probes() -> list[Probe]:
    """The services a demo cannot start without, in dependency order."""
    infrahub_url = os.getenv("INFRAHUB_URL", "http://localhost:8000").rstrip("/")
    temporal = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    prometheus_port = os.getenv("PROMETHEUS_PORT", "9090")
    grafana_port = os.getenv("GRAFANA_PORT", "3000")

    deps_hint = "uv run invoke dev.deps"
    return [
        Probe(
            name="infrahub",
            kind="http",
            # The schema API, not just port 8000: the port opens long before
            # Infrahub will accept a schema load.
            target=f"{infrahub_url}/api/schema/summary",
            hint=f"{deps_hint} (Infrahub needs 60-90s after the container starts)",
        ),
        Probe(name="temporal", kind="tcp", target=temporal, hint=deps_hint),
        Probe(
            name="prometheus",
            kind="http",
            target=f"http://localhost:{prometheus_port}/-/ready",
            hint=deps_hint,
        ),
        Probe(
            name="grafana",
            kind="http",
            target=f"http://localhost:{grafana_port}/api/health",
            hint=deps_hint,
        ),
    ]
