"""Unit tests for the presentation-layer API-key authentication (Issue #170, ADR-0005).

Tests cover:
- Parsing PRESENTATION_API_KEYS into an identity map (key -> user + role)
- Malformed entries and unknown roles are rejected at parse time
- Role hierarchy: operator satisfies viewer, viewer does not satisfy operator
"""

from __future__ import annotations

import pytest
from synapse_presentation.auth import Identity, Role, parse_api_keys


class TestParseApiKeys:
    def test_parses_multiple_entries(self) -> None:
        keys = parse_api_keys("k-alice:alice:operator,k-bob:bob:viewer")

        assert keys["k-alice"] == Identity(user="alice", role=Role.OPERATOR)
        assert keys["k-bob"] == Identity(user="bob", role=Role.VIEWER)

    def test_empty_string_yields_no_keys(self) -> None:
        assert parse_api_keys("") == {}

    def test_whitespace_around_entries_is_tolerated(self) -> None:
        keys = parse_api_keys(" k1:alice:operator , k2:bob:viewer ")

        assert set(keys) == {"k1", "k2"}

    def test_malformed_entry_raises(self) -> None:
        with pytest.raises(ValueError, match="k1:alice"):
            parse_api_keys("k1:alice")

    def test_unknown_role_raises(self) -> None:
        with pytest.raises(ValueError, match="admin"):
            parse_api_keys("k1:alice:admin")

    def test_duplicate_key_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            parse_api_keys("k1:alice:operator,k1:bob:viewer")


class TestRoleHierarchy:
    def test_operator_satisfies_viewer(self) -> None:
        assert Role.OPERATOR.satisfies(Role.VIEWER)

    def test_viewer_does_not_satisfy_operator(self) -> None:
        assert not Role.VIEWER.satisfies(Role.OPERATOR)

    def test_roles_satisfy_themselves(self) -> None:
        assert Role.VIEWER.satisfies(Role.VIEWER)
        assert Role.OPERATOR.satisfies(Role.OPERATOR)
