"""Unit tests for how the presentation service is run and configured (Issue #188).

The portal shipped in #173 with no supported way to start it, and with a
default port that ``invoke dev.deps`` guarantees is already taken. These
tests pin the operational contract:

  - The listen port does not collide with any port bound by the dev stack.
  - Host/port are overridable from the environment.
  - ``invoke presentation.start`` exists and runs the module entry point.
  - ``.env.example`` documents the variables an operator must set, including
    ``PRESENTATION_API_KEYS`` — without it every request 401s with no hint.

These are static-configuration tests in the style of ``test_collector_stack``;
no server is bound and no external dependency is required.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parents[2]
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
DEPS_COMPOSE_PATH = PROJECT_ROOT / "development" / "docker-compose-deps.yml"

DEFAULT_PRESENTATION_PORT = 8081
DEFAULT_PRESENTATION_HOST = "127.0.0.1"


@pytest.fixture(scope="module")
def env_example() -> str:
    assert ENV_EXAMPLE_PATH.exists(), f"{ENV_EXAMPLE_PATH} does not exist"
    return ENV_EXAMPLE_PATH.read_text()


@pytest.fixture(scope="module")
def deps_compose_ports() -> set[int]:
    """Every host port bound by the dev dependency stack."""
    compose = yaml.safe_load(DEPS_COMPOSE_PATH.read_text())
    host_ports: set[int] = set()
    for service in compose["services"].values():
        for mapping in service.get("ports", []) or []:
            host_side = str(mapping).split(":")[0]
            # "${TEMPORAL_UI_PORT:-8080}" -> 8080
            if ":-" in host_side:
                host_side = host_side.split(":-")[1].rstrip("}")
            host_side = host_side.strip("\"'")
            if host_side.isdigit():
                host_ports.add(int(host_side))
    return host_ports


# ---------------------------------------------------------------------------
# Listen address
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListenAddress:
    def test_default_port_is_free_in_the_dev_stack(self, deps_compose_ports: set[int]) -> None:
        """The default port must not be one docker-compose already binds.

        Regression guard for #188: the original default (8080) is Temporal's
        UI port, so the portal could never start alongside ``invoke dev.deps``
        — and the demo needs both surfaces open at once.
        """
        assert DEFAULT_PRESENTATION_PORT not in deps_compose_ports

    def test_serve_uses_documented_defaults(self) -> None:
        from synapse_presentation import main

        with patch.dict(os.environ, {}, clear=True), patch.object(main, "uvicorn") as mock_uvicorn:
            main.run()

        _, kwargs = mock_uvicorn.run.call_args
        assert kwargs["host"] == DEFAULT_PRESENTATION_HOST
        assert kwargs["port"] == DEFAULT_PRESENTATION_PORT

    def test_serve_honours_environment_overrides(self) -> None:
        from synapse_presentation import main

        overrides = {"PRESENTATION_HOST": "0.0.0.0", "PRESENTATION_PORT": "9999"}  # noqa: S104 — test value
        with patch.dict(os.environ, overrides, clear=True), patch.object(main, "uvicorn") as mock_uvicorn:
            main.run()

        _, kwargs = mock_uvicorn.run.call_args
        assert kwargs["host"] == "0.0.0.0"  # noqa: S104 — test value
        assert kwargs["port"] == 9999


# ---------------------------------------------------------------------------
# Invoke task
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvokeTask:
    def test_presentation_collection_is_registered(self) -> None:
        from tasks import ns

        assert "presentation" in ns.collections

    def test_start_task_runs_the_module_entry_point(self) -> None:
        from invoke.context import Context

        from tasks import presentation

        ctx = Context()
        with patch("tasks.presentation.execute_command") as mock_execute:
            presentation.start(ctx)

        command = mock_execute.call_args[0][1]
        assert "synapse_presentation.main" in command

    def test_start_task_passes_host_and_port_through(self) -> None:
        from invoke.context import Context

        from tasks import presentation

        ctx = Context()
        with patch("tasks.presentation.execute_command") as mock_execute:
            presentation.start(ctx, host="0.0.0.0", port=9999)  # noqa: S104 — test value

        command = mock_execute.call_args[0][1]
        assert "PRESENTATION_HOST=0.0.0.0" in command
        assert "PRESENTATION_PORT=9999" in command


# ---------------------------------------------------------------------------
# Operator-facing documentation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvExample:
    def test_api_keys_variable_is_documented(self, env_example: str) -> None:
        """Undocumented, an unset PRESENTATION_API_KEYS 401s every request."""
        assert "PRESENTATION_API_KEYS" in env_example

    def test_documented_api_keys_value_parses(self, env_example: str) -> None:
        """The example value must actually work when uncommented."""
        from synapse_presentation.auth import parse_api_keys

        entries = [
            line.split("=", 1)[1].strip()
            for line in env_example.splitlines()
            if line.strip().lstrip("# ").startswith("PRESENTATION_API_KEYS=")
        ]
        assert entries, "PRESENTATION_API_KEYS has no example value"
        identities = parse_api_keys(entries[0])
        assert identities, "example PRESENTATION_API_KEYS value yields no identities"

    def test_port_variable_is_documented(self, env_example: str) -> None:
        assert "PRESENTATION_PORT" in env_example

    def test_service_url_reference_lists_the_portal(self, env_example: str) -> None:
        assert f"http://localhost:{DEFAULT_PRESENTATION_PORT}" in env_example
