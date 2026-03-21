"""Shared fixtures for Infrahub integration tests.

Session-scoped fixtures handle schema loading and seed data population once
per test session. Tests require a running Infrahub instance.

Run with: ``INFRAHUB_URL=http://localhost:8000 pytest tests/integration/ -m integration``
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


@pytest.fixture(scope="session")
def infrahub_url():
    """Infrahub URL from environment, defaulting to localhost:8000."""
    return os.getenv("INFRAHUB_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def infrahub_token():
    """Infrahub API token from environment."""
    return os.getenv("INFRAHUB_TOKEN", "")


@pytest.fixture(scope="session")
def infrahub_client(infrahub_url, infrahub_token):
    """Session-scoped InfrahubConfigClient."""
    from network_synapse.infrahub.client import InfrahubConfigClient

    client = InfrahubConfigClient(url=infrahub_url, token=infrahub_token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def resource_manager(infrahub_url, infrahub_token):
    """Session-scoped InfrahubResourceManager."""
    from network_synapse.infrahub.resource_manager import InfrahubResourceManager

    mgr = InfrahubResourceManager(url=infrahub_url, token=infrahub_token)
    yield mgr
    mgr.close()


@pytest.fixture(scope="session", autouse=True)
def load_schemas_once(infrahub_url):
    """Load all schemas into Infrahub once per session.

    Runs ``load_schemas.py`` via subprocess so it mirrors the CI workflow.
    """
    script = BACKEND_ROOT / "network_synapse" / "scripts" / "load_schemas.py"
    if not script.exists():
        pytest.skip("load_schemas.py not found")

    result = subprocess.run(
        [sys.executable, str(script), "--url", infrahub_url],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Schema loading failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")


@pytest.fixture(scope="session", autouse=True)
def seed_data_once(infrahub_url, load_schemas_once):
    """Seed Infrahub with test data once per session.

    Uses seed_small.yml for faster execution.
    """
    script = BACKEND_ROOT / "network_synapse" / "data" / "populate_sot.py"
    seed_file = BACKEND_ROOT / "network_synapse" / "data" / "seed_small.yml"
    if not script.exists():
        pytest.skip("populate_sot.py not found")

    args = [sys.executable, str(script), "--url", infrahub_url]
    if seed_file.exists():
        args.extend(["--seed-file", str(seed_file)])

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Seed data failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
