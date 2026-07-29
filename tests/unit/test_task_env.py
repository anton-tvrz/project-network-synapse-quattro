"""Unit tests for .env loading in the invoke tasks (Issue #189).

Found by actually running `demo.up`: the readiness gate passed, then
`backend.load-schemas` died with

    RuntimeError: Missing required env vars: INFRAHUB_ADDRESS,
    INFRAHUB_API_TOKEN. See .env.example

Two separate defects behind that one line:

  1. Nothing ever loaded `.env`. Every invoke task ran with whatever
     happened to be exported in the caller's shell.
  2. `.env.example` documents INFRAHUB_URL / INFRAHUB_TOKEN (what the
     Python SDK reads) but not INFRAHUB_ADDRESS / INFRAHUB_API_TOKEN
     (what `infrahubctl` reads). So the error told the operator to consult
     a file that does not mention either variable it asked for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tasks import shared

ENV_EXAMPLE_PATH = Path(__file__).parents[2] / ".env.example"

# infrahubctl reads these; tasks/backend.py load_schemas requires them.
INFRAHUBCTL_VARS = ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN")


@pytest.fixture(scope="module")
def env_example() -> str:
    return ENV_EXAMPLE_PATH.read_text()


@pytest.mark.unit
class TestLoadEnvFile:
    def test_reads_values_from_the_env_file(self, tmp_path: Path, monkeypatch) -> None:
        env = tmp_path / ".env"
        env.write_text("FOO=bar\n")
        monkeypatch.delenv("FOO", raising=False)
        shared.load_env_file(env)
        import os

        assert os.environ["FOO"] == "bar"

    def test_does_not_override_the_callers_environment(self, tmp_path: Path, monkeypatch) -> None:
        """An explicit `FOO=x uv run invoke ...` must win over the file."""
        env = tmp_path / ".env"
        env.write_text("FOO=from-file\n")
        monkeypatch.setenv("FOO", "from-shell")
        shared.load_env_file(env)
        import os

        assert os.environ["FOO"] == "from-shell"

    def test_missing_file_is_not_an_error(self, tmp_path: Path) -> None:
        """A fresh clone has no .env; tasks not needing one must still run."""
        shared.load_env_file(tmp_path / "does-not-exist")

    def test_ignores_comments_and_blank_lines(self, tmp_path: Path, monkeypatch) -> None:
        env = tmp_path / ".env"
        env.write_text("# a comment\n\nFOO=bar\n")
        monkeypatch.delenv("FOO", raising=False)
        shared.load_env_file(env)
        import os

        assert os.environ["FOO"] == "bar"


@pytest.mark.unit
class TestInfrahubctlEnvFallback:
    """`load-schemas` should work from the SDK-style vars alone.

    The dual naming is an infrahubctl-vs-SDK detail, not something an
    operator should have to know. Anyone who set up from the older docs has
    only INFRAHUB_URL / INFRAHUB_TOKEN.
    """

    def test_derives_address_and_token_from_the_sdk_names(self, monkeypatch) -> None:
        import os

        from tasks import backend

        monkeypatch.delenv("INFRAHUB_ADDRESS", raising=False)
        monkeypatch.delenv("INFRAHUB_API_TOKEN", raising=False)
        monkeypatch.setenv("INFRAHUB_URL", "http://localhost:8000")
        monkeypatch.setenv("INFRAHUB_TOKEN", "tok")

        backend.ensure_infrahubctl_env()

        assert os.environ["INFRAHUB_ADDRESS"] == "http://localhost:8000"
        assert os.environ["INFRAHUB_API_TOKEN"] == "tok"

    def test_explicit_infrahubctl_vars_win(self, monkeypatch) -> None:
        import os

        from tasks import backend

        monkeypatch.setenv("INFRAHUB_ADDRESS", "http://explicit:9000")
        monkeypatch.setenv("INFRAHUB_API_TOKEN", "explicit-token")
        monkeypatch.setenv("INFRAHUB_URL", "http://localhost:8000")
        monkeypatch.setenv("INFRAHUB_TOKEN", "tok")

        backend.ensure_infrahubctl_env()

        assert os.environ["INFRAHUB_ADDRESS"] == "http://explicit:9000"
        assert os.environ["INFRAHUB_API_TOKEN"] == "explicit-token"

    def test_reports_what_is_missing_when_nothing_is_set(self, monkeypatch) -> None:
        from tasks import backend

        for var in ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN", "INFRAHUB_URL", "INFRAHUB_TOKEN"):
            monkeypatch.delenv(var, raising=False)

        with pytest.raises(RuntimeError) as excinfo:
            backend.ensure_infrahubctl_env()
        assert "INFRAHUB_ADDRESS" in str(excinfo.value)


@pytest.mark.unit
class TestEnvExampleCoversInfrahubctl:
    @pytest.mark.parametrize("var", INFRAHUBCTL_VARS)
    def test_documents_the_vars_load_schemas_requires(self, env_example: str, var: str) -> None:
        """`load-schemas` errors point at .env.example — it must contain them."""
        assert var in env_example

    def test_infrahubctl_and_sdk_addresses_agree(self, env_example: str) -> None:
        """INFRAHUB_ADDRESS and INFRAHUB_URL must not drift apart silently."""
        values = {}
        for line in env_example.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip()
        assert values.get("INFRAHUB_ADDRESS") == values.get("INFRAHUB_URL")
