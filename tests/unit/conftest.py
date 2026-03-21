"""Unit test configuration — mocks for Infrahub SDK git dependencies."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_dulwich_active_branch():
    """Mock dulwich active_branch to avoid git HEAD resolution failures in CI.

    The Infrahub SDK checks and transforms resolve git active_branch via dulwich
    during log_info/log_error (checks) and __init__ (transforms). In CI's detached
    HEAD state this raises IndexError. Mocking it globally for unit tests is safe
    since we never test git branch resolution logic here.
    """
    with patch("dulwich.porcelain.active_branch", return_value=b"test-branch"):
        yield
