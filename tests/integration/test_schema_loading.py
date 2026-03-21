"""Integration tests for Infrahub schema loading.

Validates that all project schemas load correctly into a real Infrahub instance.
Requires running Infrahub (started via docker-compose-ci.yml or development stack).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


@pytest.mark.integration
class TestSchemaLoading:
    """Test schema loading into Infrahub."""

    def test_schema_summary_contains_expected_nodes(self, infrahub_url):
        """After loading, schema summary includes all project node types."""
        resp = httpx.get(f"{infrahub_url}/api/schema/summary", timeout=15.0)
        assert resp.status_code == 200

        # Check a subset of expected schema nodes
        expected = {"DcimDevice", "InterfacePhysical", "RoutingBGPSession", "IpamIPAddress"}
        # Schema summary format varies — check in the full response text as fallback
        response_text = resp.text
        for node in expected:
            assert node in response_text, f"Expected node '{node}' not found in schema summary"

    def test_schema_load_is_idempotent(self, infrahub_url):
        """Loading schemas a second time succeeds without errors."""
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
        assert result.returncode == 0, f"Idempotent reload failed: {result.stderr}"

    def test_schema_summary_endpoint_accessible(self, infrahub_url):
        """The schema summary API endpoint is accessible and returns JSON."""
        resp = httpx.get(f"{infrahub_url}/api/schema/summary", timeout=15.0)
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("application/json")
