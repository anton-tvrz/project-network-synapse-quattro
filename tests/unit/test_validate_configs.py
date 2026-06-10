"""Unit tests for the post-deploy validation stubs.

`validate_configs.py` currently holds unimplemented gNMI validation stubs.
These characterization tests pin the current (no-op) contract so the module
is covered and any future implementation has a failing-test starting point.
"""

from __future__ import annotations

import pytest

from network_synapse.scripts.validate_configs import (
    validate_bgp_sessions,
    validate_interfaces,
)


@pytest.mark.unit
def test_validate_bgp_sessions_is_callable_stub() -> None:
    """Stub returns None until gNMI validation is implemented."""
    assert validate_bgp_sessions("leaf01") is None


@pytest.mark.unit
def test_validate_interfaces_is_callable_stub() -> None:
    """Stub returns None until gNMI validation is implemented."""
    assert validate_interfaces("leaf01") is None
