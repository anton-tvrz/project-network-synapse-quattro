"""Unit tests for the orphaned firewall rule check (#44).

An orphan is a FirewallRuleSet still deployed on a device while the
ConnectivityIntent that justified it has been decommissioned. The schema makes
the other orphan class impossible — FirewallRuleSet.binding is mandatory — so
these tests cover the reachable condition only.
"""

from __future__ import annotations

import pytest

from network_synapse.checks.orphaned_rules_check import OrphanedRulesCheck


def _make_rule(
    *,
    name: str = "legacy-reporting-permit",
    rule_name: str = "permit-legacy-5432",
    action: str = "permit",
    sequence: int = 200,
) -> dict:
    """Build a mock FirewallRuleSet edge."""
    return {
        "node": {
            "id": f"rule-{name[:8]}",
            "name": {"value": name},
            "rule_name": {"value": rule_name},
            "action": {"value": action},
            "sequence": {"value": sequence},
        }
    }


def _make_binding(
    *,
    name: str = "legacy-reporting-to-archive-leaf02",
    device: str = "leaf02",
    rules: list[dict] | None = None,
) -> dict:
    """Build a mock InfrastructureBinding edge carrying rule sets."""
    return {
        "node": {
            "id": f"binding-{name[:8]}",
            "name": {"value": name},
            "device": {"node": {"name": {"value": device}}},
            "rule_sets": {"edges": rules if rules is not None else [_make_rule()]},
        }
    }


def _make_intent(
    *,
    name: str = "legacy-reporting-to-archive",
    decommissioned_at: str | None = "2026-06-15T09:00:00Z",
    owner: str = "risk-reporting-team",
    origin: str = "CHG-0455",
    bindings: list[dict] | None = None,
) -> dict:
    """Build a mock decommissioned ConnectivityIntent edge."""
    return {
        "node": {
            "id": f"intent-{name[:8]}",
            "name": {"value": name},
            "decommissioned_at": {"value": decommissioned_at},
            "owner": {"value": owner},
            "origin": {"value": origin},
            "bindings": {"edges": bindings if bindings is not None else [_make_binding()]},
        }
    }


def _data(intents: list[dict]) -> dict:
    """Wrap intent edges in the query's response envelope."""
    return {"ConnectivityIntent": {"edges": intents}}


@pytest.mark.unit
class TestOrphanedRulesCheck:
    """Detection of firewall rules outliving their intent."""

    @pytest.mark.asyncio
    async def test_no_decommissioned_intents_passes(self):
        """A fabric with nothing retired has no orphans."""
        check = OrphanedRulesCheck()
        await check.validate(_data([]))
        assert not check.errors

    @pytest.mark.asyncio
    async def test_decommissioned_intent_without_rules_passes(self):
        """A retired intent whose rules were reaped is clean, not an orphan."""
        check = OrphanedRulesCheck()
        binding = _make_binding(rules=[])
        await check.validate(_data([_make_intent(bindings=[binding])]))
        assert not check.errors

    @pytest.mark.asyncio
    async def test_decommissioned_intent_without_bindings_passes(self):
        """A retired intent with no bindings left cannot have orphaned rules."""
        check = OrphanedRulesCheck()
        await check.validate(_data([_make_intent(bindings=[])]))
        assert not check.errors

    @pytest.mark.asyncio
    async def test_rule_outliving_intent_is_flagged(self):
        """The core violation: rule still deployed, intent decommissioned."""
        check = OrphanedRulesCheck()
        await check.validate(_data([_make_intent()]))
        assert len(check.errors) == 1

    @pytest.mark.asyncio
    async def test_violation_names_rule_device_and_intent(self):
        """The report must identify what to remove and where it lives."""
        check = OrphanedRulesCheck()
        await check.validate(_data([_make_intent()]))
        message = str(check.errors[0])
        assert "permit-legacy-5432" in message
        assert "leaf02" in message
        assert "legacy-reporting-to-archive" in message

    @pytest.mark.asyncio
    async def test_violation_reports_retirement_date(self):
        """How long a rule has lingered is what makes it an audit finding."""
        check = OrphanedRulesCheck()
        await check.validate(_data([_make_intent()]))
        assert "2026-06-15" in str(check.errors[0])

    @pytest.mark.asyncio
    async def test_violation_anchors_to_the_rule_object(self):
        """Errors must anchor to the rule, since that is what gets deleted."""
        check = OrphanedRulesCheck()
        await check.validate(_data([_make_intent()]))
        assert check.errors[0]["object_type"] == "FirewallRuleSet"
        assert check.errors[0]["object_id"] == _make_rule()["node"]["id"]

    @pytest.mark.asyncio
    async def test_every_orphaned_rule_is_reported_separately(self):
        """Two rules under one binding are two findings, not one."""
        check = OrphanedRulesCheck()
        rules = [
            _make_rule(name="legacy-permit-a", rule_name="permit-a"),
            _make_rule(name="legacy-permit-b", rule_name="permit-b"),
        ]
        await check.validate(_data([_make_intent(bindings=[_make_binding(rules=rules)])]))
        assert len(check.errors) == 2
        reported = " ".join(str(e) for e in check.errors)
        assert "permit-a" in reported
        assert "permit-b" in reported

    @pytest.mark.asyncio
    async def test_orphans_across_multiple_bindings_are_reported(self):
        """One intent realised on two devices leaves an orphan on each."""
        check = OrphanedRulesCheck()
        bindings = [
            _make_binding(name="legacy-leaf01", device="leaf01"),
            _make_binding(name="legacy-leaf02", device="leaf02"),
        ]
        await check.validate(_data([_make_intent(bindings=bindings)]))
        assert len(check.errors) == 2
        reported = " ".join(str(e) for e in check.errors)
        assert "leaf01" in reported
        assert "leaf02" in reported

    @pytest.mark.asyncio
    async def test_deny_rules_are_orphans_too(self):
        """A stale deny is still drift — the check is not permit-only."""
        check = OrphanedRulesCheck()
        rules = [_make_rule(action="deny", rule_name="deny-legacy-5432")]
        await check.validate(_data([_make_intent(bindings=[_make_binding(rules=rules)])]))
        assert len(check.errors) == 1
        assert "deny" in str(check.errors[0])

    @pytest.mark.asyncio
    async def test_missing_retirement_date_still_flags_the_rule(self):
        """A null decommissioned_at must not suppress the violation."""
        check = OrphanedRulesCheck()
        await check.validate(_data([_make_intent(decommissioned_at=None)]))
        assert len(check.errors) == 1
        assert "permit-legacy-5432" in str(check.errors[0])

    @pytest.mark.asyncio
    async def test_missing_device_still_flags_the_rule(self):
        """A binding with no resolvable device is reported, not skipped."""
        check = OrphanedRulesCheck()
        binding = _make_binding()
        binding["node"]["device"] = {"node": None}
        await check.validate(_data([_make_intent(bindings=[binding])]))
        assert len(check.errors) == 1
        assert "unknown" in str(check.errors[0]).lower()

    @pytest.mark.asyncio
    async def test_clean_fabric_logs_an_explicit_pass(self):
        """An empty result must read as 'verified clean', not 'did not run'."""
        check = OrphanedRulesCheck()
        await check.validate(_data([]))
        assert check.logs
        assert "no decommissioned" in str(check.logs[0]["message"]).lower()

    @pytest.mark.asyncio
    async def test_owner_is_reported_for_remediation(self):
        """Findings route to a team, so the owner belongs in the message."""
        check = OrphanedRulesCheck()
        await check.validate(_data([_make_intent()]))
        assert "risk-reporting-team" in str(check.errors[0])
