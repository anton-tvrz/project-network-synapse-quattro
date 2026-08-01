"""Integration tests for the orphaned firewall rule check (#44).

The unit tests drive the check with hand-written mocks. What they cannot prove
is that `decommissioned_intents.gql` is valid against the live schema, that the
one-hop filter limitation is actually worked around, and that Infrahub's real
response shape matches what the check parses. That is what these cover.

The check is constructed with an explicit `branch`. Every log call reads
`InfrahubCheck.branch_name`, which otherwise asks git for the active branch and
raises `IndexError` on a detached HEAD — how CI checks out pull requests.
Infrahub supplies the branch when it runs the check for real.

Scope note: the session fixture seeds `seed_small.yml`, which has no `leaf02`.
The business-intent bindings target `leaf02`, so they — and the firewall rules
hanging off them — are skipped here. A detected orphan therefore cannot be
asserted in this environment; that path is covered by the unit tests. These
tests assert the query and the check work against the real schema, which is the
part mocks cannot vouch for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from network_synapse.checks.orphaned_rules_check import OrphanedRulesCheck

QUERY_PATH = (
    Path(__file__).resolve().parents[2] / "backend" / "network_synapse" / "queries" / "decommissioned_intents.gql"
)


@pytest.fixture(scope="module")
def decommissioned_intents_result(infrahub_client):
    """Run the registered orphan-detection query against live Infrahub."""
    return infrahub_client._graphql(QUERY_PATH.read_text())


@pytest.mark.integration
class TestDecommissionedIntentsQuery:
    """The .gql registered in .infrahub.yml must work against the real schema."""

    def test_query_is_valid_against_live_schema(self, decommissioned_intents_result):
        """An invalid field or filter would raise GraphQL errors, not return data."""
        assert "ConnectivityIntent" in decommissioned_intents_result

    def test_filter_returns_only_decommissioned_intents(self, decommissioned_intents_result):
        """The inverted detection depends on this filter actually narrowing."""
        edges = decommissioned_intents_result["ConnectivityIntent"]["edges"]
        assert edges, "seeded legacy-reporting-to-archive intent should be returned"

        names = [edge["node"]["name"]["value"] for edge in edges]
        assert "legacy-reporting-to-archive" in names
        assert "trading-gw-to-market-data" not in names, "active intent must be filtered out"

    def test_retired_intent_carries_audit_metadata(self, decommissioned_intents_result):
        """The check reports these fields, so they must survive the round trip."""
        edges = decommissioned_intents_result["ConnectivityIntent"]["edges"]
        intent = next(edge["node"] for edge in edges if edge["node"]["name"]["value"] == "legacy-reporting-to-archive")
        assert intent["decommissioned_at"]["value"].startswith("2026-06-15")
        assert intent["owner"]["value"] == "risk-reporting-team"


@pytest.mark.integration
class TestOrphanedRulesCheckAgainstLiveData:
    """The check must parse Infrahub's real response shape."""

    @pytest.mark.asyncio
    async def test_check_runs_against_live_response(self, decommissioned_intents_result):
        """A shape mismatch between mocks and Infrahub would surface here."""
        check = OrphanedRulesCheck(branch="main")
        await check.validate(decommissioned_intents_result)
        assert check.logs, "check must report something, even on a clean fabric"

    @pytest.mark.asyncio
    async def test_every_reported_orphan_is_actionable(self, decommissioned_intents_result):
        """Whatever is flagged must name the object an operator has to delete."""
        check = OrphanedRulesCheck(branch="main")
        await check.validate(decommissioned_intents_result)

        for error in check.errors:
            assert error["object_type"] == "FirewallRuleSet"
            assert error["object_id"]
