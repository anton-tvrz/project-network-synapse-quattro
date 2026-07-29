"""Unit tests for infrastructure readiness probing (Issue #189).

`invoke dev.deps` returns as soon as Docker has *started* 16 containers, but
Infrahub needs 60-90s after that before it will serve schema writes. Nothing
gated on this, so `backend.load-schemas` raced a cold Infrahub — the most
likely way a demo dies in its first two minutes.

These tests pin the polling contract. Clock and sleep are injected so the
timeout logic is tested without real waiting; the probes themselves are
exercised against a local socket rather than mocked away entirely.
"""

from __future__ import annotations

import socket
from dataclasses import replace

import pytest

from network_synapse import readiness


@pytest.fixture
def fake_clock() -> readiness.Clock:
    """A monotonic clock that only advances when sleep() is called."""

    class Clock:
        def __init__(self) -> None:
            self.t = 0.0
            self.slept: list[float] = []

        def now(self) -> float:
            return self.t

        def sleep(self, seconds: float) -> None:
            self.slept.append(seconds)
            self.t += seconds

    return Clock()


def _probe(name: str = "svc") -> readiness.Probe:
    return readiness.Probe(name=name, kind="tcp", target="127.0.0.1:1", hint="start it")


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTcpProbe:
    def test_open_port_is_ready(self) -> None:
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            ready, _ = readiness.probe_tcp("127.0.0.1", port, timeout=1.0)
        assert ready is True

    def test_closed_port_is_not_ready(self) -> None:
        # Bind then close, so the port is almost certainly unused.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        ready, detail = readiness.probe_tcp("127.0.0.1", port, timeout=0.5)
        assert ready is False
        assert detail

    def test_unreachable_host_reports_not_ready_rather_than_raising(self) -> None:
        """A down service is an expected state, not an exception."""
        ready, detail = readiness.probe_tcp("no-such-host.invalid", 9999, timeout=0.5)
        assert ready is False
        assert detail


@pytest.mark.unit
class TestHttpProbe:
    def test_connection_error_is_not_ready(self) -> None:
        ready, detail = readiness.probe_http("http://127.0.0.1:1/nothing", timeout=0.5)
        assert ready is False
        assert detail

    def test_server_error_status_is_not_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Infrahub answers 500 while still warming up — that is not ready."""

        class Response:
            status_code = 500

        monkeypatch.setattr(readiness.httpx, "get", lambda *a, **k: Response())
        ready, detail = readiness.probe_http("http://x/health", timeout=0.5)
        assert ready is False
        assert "500" in detail

    def test_success_status_is_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Response:
            status_code = 200

        monkeypatch.setattr(readiness.httpx, "get", lambda *a, **k: Response())
        ready, _ = readiness.probe_http("http://x/health", timeout=0.5)
        assert ready is True


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWaitUntilReady:
    def test_returns_immediately_when_everything_is_already_up(self, fake_clock) -> None:
        results = readiness.wait_until_ready(
            [_probe("a"), _probe("b")],
            timeout=300,
            interval=5,
            clock=fake_clock,
            run=lambda probe, timeout: readiness.ProbeResult(probe, True, "ok"),
        )
        assert all(r.ready for r in results)
        assert fake_clock.slept == [], "should not sleep once everything is ready"

    def test_polls_until_the_slow_service_comes_up(self, fake_clock) -> None:
        """The Infrahub warm-up case: down for a while, then up."""
        attempts = {"n": 0}

        def run(probe: readiness.Probe, timeout: float) -> readiness.ProbeResult:
            attempts["n"] += 1
            return readiness.ProbeResult(probe, attempts["n"] >= 3, "")

        results = readiness.wait_until_ready([_probe()], timeout=300, interval=5, clock=fake_clock, run=run)
        assert all(r.ready for r in results)
        assert attempts["n"] == 3
        assert fake_clock.slept == [5, 5]

    def test_gives_up_after_the_timeout_and_reports_what_is_down(self, fake_clock) -> None:
        """A timeout must return a diagnosis, not raise or hang."""
        results = readiness.wait_until_ready(
            [_probe("infrahub")],
            timeout=20,
            interval=5,
            clock=fake_clock,
            run=lambda probe, timeout: readiness.ProbeResult(probe, False, "connection refused"),
        )
        assert [r.ready for r in results] == [False]
        assert results[0].probe.name == "infrahub"
        assert fake_clock.now() <= 20 + 5

    def test_ready_services_are_not_reprobed(self, fake_clock) -> None:
        """Don't hammer services that already answered."""
        calls: list[str] = []

        def run(probe: readiness.Probe, timeout: float) -> readiness.ProbeResult:
            calls.append(probe.name)
            return readiness.ProbeResult(probe, probe.name == "fast", "")

        readiness.wait_until_ready(
            [_probe("fast"), _probe("slow")],
            timeout=10,
            interval=5,
            clock=fake_clock,
            run=run,
        )
        assert calls.count("fast") == 1
        assert calls.count("slow") > 1

    def test_results_preserve_probe_order(self, fake_clock) -> None:
        probes = [_probe("a"), _probe("b"), _probe("c")]
        results = readiness.wait_until_ready(
            probes,
            timeout=10,
            interval=5,
            clock=fake_clock,
            run=lambda probe, timeout: readiness.ProbeResult(probe, True, ""),
        )
        assert [r.probe.name for r in results] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# The demo stack definition
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDemoProbes:
    def test_covers_the_services_the_demo_depends_on(self) -> None:
        names = {probe.name for probe in readiness.demo_probes()}
        assert {"infrahub", "temporal", "prometheus", "grafana"} <= names

    def test_infrahub_probe_targets_the_schema_api(self) -> None:
        """`load-schemas` writes to /api/schema — a TCP check on 8000 would
        pass while Infrahub was still returning 500s to schema requests."""
        infrahub = next(p for p in readiness.demo_probes() if p.name == "infrahub")
        assert infrahub.kind == "http"
        assert "/api/schema" in infrahub.target

    def test_every_probe_carries_a_remediation_hint(self) -> None:
        """A failed readiness check must tell the operator what to run."""
        for probe in readiness.demo_probes():
            assert probe.hint, f"{probe.name} has no hint"

    def test_ports_follow_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INFRAHUB_URL", "http://elsewhere:9001")
        infrahub = next(p for p in readiness.demo_probes() if p.name == "infrahub")
        assert infrahub.target.startswith("http://elsewhere:9001")


@pytest.mark.unit
class TestReporting:
    def test_summary_lists_down_services_with_their_hints(self) -> None:
        probe = replace(_probe("infrahub"), hint="uv run invoke dev.deps")
        results = [
            readiness.ProbeResult(_probe("temporal"), True, ""),
            readiness.ProbeResult(probe, False, "connection refused"),
        ]
        summary = readiness.format_summary(results)
        assert "infrahub" in summary
        assert "connection refused" in summary
        assert "uv run invoke dev.deps" in summary

    def test_all_ready_returns_true_only_when_everything_is_up(self) -> None:
        up = readiness.ProbeResult(_probe("a"), True, "")
        down = readiness.ProbeResult(_probe("b"), False, "")
        assert readiness.all_ready([up]) is True
        assert readiness.all_ready([up, down]) is False
        assert readiness.all_ready([]) is True
