"""Unit tests for the demo bring-up tasks (Issue #189).

Bringing the platform up was seven manual steps across three documents with
no readiness signal anywhere. These tests pin the three properties that make
`demo.up` worth having over a shell alias:

  1. Readiness is checked *between* starting the stack and using it — the
     race that `load-schemas` lost against a cold Infrahub.
  2. A readiness timeout aborts rather than proceeding into a failure that
     surfaces later as a confusing schema error.
  3. `demo.reset` is destructive and does nothing without explicit consent.
"""

from __future__ import annotations

import pytest
from invoke import Exit
from invoke.context import Context

from network_synapse.readiness import Probe, ProbeResult
from tasks import demo


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Context:
    """A context with Docker up and no pre-existing lab; override per-test."""
    monkeypatch.setattr(demo, "_docker_available", lambda ctx: True)
    monkeypatch.setattr(demo, "_lab_containers_exist", lambda ctx: False)
    return Context()


@pytest.fixture
def commands(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every shell command a task would run, running none of them."""
    recorded: list[str] = []
    monkeypatch.setattr(demo, "execute_command", lambda ctx, cmd, **kw: recorded.append(cmd))
    return recorded


def _probe(name: str) -> Probe:
    return Probe(name=name, kind="tcp", target="localhost:1", hint="hint")


def _ready(monkeypatch: pytest.MonkeyPatch, ready: bool) -> list[str]:
    """Stub readiness polling; returns the list that records when it was called."""
    call_order: list[str] = []

    def fake_wait(probes, **kwargs):
        call_order.append("readiness")
        return [ProbeResult(_probe("infrahub"), ready, "" if ready else "connection refused")]

    monkeypatch.setattr(demo, "wait_until_ready", fake_wait)
    return call_order


# ---------------------------------------------------------------------------
# demo.up
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDemoUp:
    def test_starts_the_stack_before_waiting_on_it(self, ctx, commands, monkeypatch) -> None:
        order = _ready(monkeypatch, ready=True)
        monkeypatch.setattr(demo, "execute_command", lambda c, cmd, **kw: (commands.append(cmd), order.append(cmd))[0])
        demo.up(ctx)
        compose_at = next(i for i, step in enumerate(order) if "compose" in step and "up -d" in step)
        assert compose_at < order.index("readiness")

    def test_fails_fast_with_a_clear_message_when_docker_is_down(self, commands, monkeypatch) -> None:
        """`docker compose` against a dead daemon reports a socket path, not a cause."""
        monkeypatch.setattr(demo, "_docker_available", lambda ctx: False)
        with pytest.raises(Exit) as excinfo:
            demo.up(Context())
        assert "OrbStack" in str(excinfo.value.message)
        assert commands == []

    def test_waits_for_readiness_before_loading_schemas(self, ctx, commands, monkeypatch) -> None:
        """The whole point: load-schemas must not race a cold Infrahub."""
        order = _ready(monkeypatch, ready=True)
        monkeypatch.setattr(demo, "execute_command", lambda c, cmd, **kw: (commands.append(cmd), order.append(cmd))[0])
        demo.up(ctx)
        readiness_at = order.index("readiness")
        schema_at = next(i for i, step in enumerate(order) if "load-schemas" in step)
        assert readiness_at < schema_at

    def test_seeds_data_after_schemas(self, ctx, commands, monkeypatch) -> None:
        _ready(monkeypatch, ready=True)
        demo.up(ctx)
        schema_at = next(i for i, cmd in enumerate(commands) if "load-schemas" in cmd)
        seed_at = next(i for i, cmd in enumerate(commands) if "seed-data" in cmd)
        assert schema_at < seed_at

    def test_deploys_the_lab(self, ctx, commands, monkeypatch) -> None:
        _ready(monkeypatch, ready=True)
        demo.up(ctx)
        assert any("lab-deploy" in cmd for cmd in commands)

    def test_aborts_without_loading_schemas_when_readiness_times_out(self, ctx, commands, monkeypatch) -> None:
        """Proceeding into a cold stack produces a confusing downstream error."""
        _ready(monkeypatch, ready=False)
        with pytest.raises(Exit):
            demo.up(ctx)
        assert not any("load-schemas" in cmd for cmd in commands)
        assert not any("seed-data" in cmd for cmd in commands)

    def test_skip_lab_leaves_the_lab_alone(self, ctx, commands, monkeypatch) -> None:
        _ready(monkeypatch, ready=True)
        demo.up(ctx, skip_lab=True)
        assert not any("lab-deploy" in cmd for cmd in commands)

    def test_reconfigures_an_existing_lab_instead_of_failing(self, ctx, commands, monkeypatch) -> None:
        """Re-running is the normal case when rehearsing a demo.

        Plain `containerlab deploy` aborts with "containers already exist" —
        including when the lab is in a stale half-state, which is exactly
        when you most want to re-run.
        """
        _ready(monkeypatch, ready=True)
        monkeypatch.setattr(demo, "_lab_containers_exist", lambda ctx: True)
        demo.up(ctx)
        deploy = next(cmd for cmd in commands if "lab-deploy" in cmd)
        assert "--reconfigure" in deploy

    def test_waits_for_gnmi_after_deploying_the_lab(self, ctx, commands, monkeypatch) -> None:
        """containerlab returns before SR Linux gNMI is listening."""
        order = _ready(monkeypatch, ready=True)
        monkeypatch.setattr(demo, "execute_command", lambda c, cmd, **kw: (commands.append(cmd), order.append(cmd))[0])
        demo.up(ctx)
        deploy_at = next(i for i, step in enumerate(order) if "lab-deploy" in step)
        # readiness is recorded twice: stack first, lab second
        assert order.count("readiness") == 2
        assert order.index("readiness", deploy_at) > deploy_at

    def test_aborts_when_gnmi_never_comes_up(self, ctx, commands, monkeypatch) -> None:
        calls = {"n": 0}

        def fake_wait(probes, **kwargs):
            calls["n"] += 1
            # stack ready, lab never ready
            ok = calls["n"] == 1
            return [ProbeResult(_probe("spine01"), ok, "" if ok else "connection refused")]

        monkeypatch.setattr(demo, "wait_until_ready", fake_wait)
        with pytest.raises(Exit):
            demo.up(ctx)

    def test_deploys_cleanly_when_no_lab_exists(self, ctx, commands, monkeypatch) -> None:
        _ready(monkeypatch, ready=True)
        monkeypatch.setattr(demo, "_lab_containers_exist", lambda ctx: False)
        demo.up(ctx)
        deploy = next(cmd for cmd in commands if "lab-deploy" in cmd)
        assert "--reconfigure" not in deploy


# ---------------------------------------------------------------------------
# demo.status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDemoStatus:
    def test_succeeds_when_everything_is_up(self, ctx, monkeypatch, capsys) -> None:
        monkeypatch.setattr(demo, "check_now", lambda: [ProbeResult(_probe("infrahub"), True, "")])
        demo.status(ctx)
        assert "infrahub" in capsys.readouterr().out

    def test_exits_nonzero_when_something_is_down(self, ctx, monkeypatch) -> None:
        """Runnable as a pre-demo go/no-go gate, so it must fail loudly."""
        monkeypatch.setattr(demo, "check_now", lambda: [ProbeResult(_probe("infrahub"), False, "refused")])
        with pytest.raises(Exit) as excinfo:
            demo.status(ctx)
        assert excinfo.value.code != 0

    def test_reports_the_remediation_hint_for_a_down_service(self, ctx, monkeypatch, capsys) -> None:
        probe = Probe(name="infrahub", kind="tcp", target="localhost:8000", hint="uv run invoke dev.deps")
        monkeypatch.setattr(demo, "check_now", lambda: [ProbeResult(probe, False, "refused")])
        with pytest.raises(Exit):
            demo.status(ctx)
        assert "uv run invoke dev.deps" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# demo.reset
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDemoReset:
    def test_does_nothing_without_explicit_consent(self, ctx, commands, monkeypatch) -> None:
        """Reset destroys every volume — Infrahub data, Temporal history, metrics."""
        monkeypatch.setattr(demo, "_confirm", lambda prompt: False)
        with pytest.raises(Exit):
            demo.reset(ctx)
        assert commands == []

    def test_yes_flag_skips_the_prompt(self, ctx, commands, monkeypatch) -> None:
        def refuse(prompt: str) -> bool:  # must not be consulted
            raise AssertionError("--yes should not prompt")

        monkeypatch.setattr(demo, "_confirm", refuse)
        demo.reset(ctx, yes=True)
        assert commands

    def test_destroys_the_lab_and_removes_volumes(self, ctx, commands, monkeypatch) -> None:
        monkeypatch.setattr(demo, "_confirm", lambda prompt: True)
        demo.reset(ctx)
        joined = " ".join(commands)
        assert "lab-destroy" in joined
        assert "-v" in joined or "--volumes" in joined

    def test_tears_down_the_lab_before_removing_volumes(self, ctx, commands, monkeypatch) -> None:
        """Destroying containerlab after the network is gone leaves orphans."""
        monkeypatch.setattr(demo, "_confirm", lambda prompt: True)
        demo.reset(ctx)
        lab_at = next(i for i, cmd in enumerate(commands) if "lab-destroy" in cmd)
        volumes_at = next(i for i, cmd in enumerate(commands) if "down" in cmd and ("-v" in cmd or "--volumes" in cmd))
        assert lab_at < volumes_at
