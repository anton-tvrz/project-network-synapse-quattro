"""Infrahub Check: orphaned firewall rules (#44).

Every FirewallRuleSet must trace back to an active ConnectivityIntent. A rule
that outlives the intent justifying it is a compliance violation: it is still
permitting or denying traffic on a device with no business reason on record.

Detection is inverted deliberately. The natural phrasing — filtering rules by
`binding__intent__status__value` — does not work, because Infrahub's GraphQL
filters traverse only one relationship hop. So the query selects decommissioned
intents and walks *down* to the rules still hanging off them.

The other orphan class, a rule with no binding at all, is unreachable:
FirewallRuleSet.binding is mandatory, so the schema prevents it.

Registered in .infrahub.yml as 'validate_orphaned_rules'.
"""

from __future__ import annotations

from typing import Any

from infrahub_sdk.checks import InfrahubCheck

UNKNOWN = "unknown"


def _value(container: dict | None, key: str, default: str = UNKNOWN) -> Any:
    """Read `container[key]['value']`, tolerating nulls anywhere on the path."""
    if not container:
        return default
    attribute = container.get(key)
    if not attribute:
        return default
    value = attribute.get("value")
    return default if value is None else value


class OrphanedRulesCheck(InfrahubCheck):
    """Flag firewall rules still deployed for decommissioned intents."""

    query = "decommissioned_intents"

    async def validate(self, data: dict) -> None:
        """Report one violation per rule outliving its intent."""
        intent_edges = data.get("ConnectivityIntent", {}).get("edges", [])

        if not intent_edges:
            self.log_info(message="No decommissioned intents found — no orphaned rules possible")
            return

        orphan_count = 0

        for intent_edge in intent_edges:
            intent = intent_edge["node"]
            intent_name = _value(intent, "name")
            owner = _value(intent, "owner")
            # A retired intent with no date is still retired — report the rule
            # rather than letting missing metadata hide the violation.
            retired_at = _value(intent, "decommissioned_at", default="date unrecorded")

            for binding_edge in intent.get("bindings", {}).get("edges", []):
                binding = binding_edge["node"]
                device_node = (binding.get("device") or {}).get("node")
                device = _value(device_node, "name")

                for rule_edge in binding.get("rule_sets", {}).get("edges", []):
                    rule = rule_edge["node"]
                    orphan_count += 1
                    self.log_error(
                        message=(
                            f"Orphaned firewall rule '{_value(rule, 'rule_name')}' "
                            f"({_value(rule, 'action')}, seq {_value(rule, 'sequence')}) "
                            f"still deployed on '{device}' for decommissioned intent "
                            f"'{intent_name}' (retired {retired_at}, owner {owner})"
                        ),
                        object_id=rule.get("id", UNKNOWN),
                        object_type="FirewallRuleSet",
                    )

        if not orphan_count:
            self.log_info(message=(f"{len(intent_edges)} decommissioned intent(s) checked — no rules left behind"))
