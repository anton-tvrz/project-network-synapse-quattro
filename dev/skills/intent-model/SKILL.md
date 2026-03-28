# Intent Model — Business & Operational Intent Skill

## Metadata
- name: intent-model
- triggers: intent, lineage, business intent, operational override, connectivity, firewall rule, compliance
- project: Network Synapse Quattro

## Overview

NSQuattro's intent model creates data lineage from business need to device configuration. It has two parts:
1. **Business Intent Bridge** — 5-object chain from application owner to firewall rule
2. **Operational Intent** — 3-object model for time-bounded overrides with auto-reversion

## Business Intent Chain (5 Objects)

```
ApplicationService → ServiceEndpoint → ConnectivityIntent → InfrastructureBinding → FirewallRuleSet
```

| Schema Object | Purpose | Key Attributes |
|---------------|---------|----------------|
| **ApplicationService** | Business-level service declaration | name, owner, environment, criticality (P1-P4) |
| **ServiceEndpoint** | Protocol/port endpoint within a service | protocol (TCP/UDP/ICMP), port, direction |
| **ConnectivityIntent** | Declared need for two endpoints to communicate | status (requested/approved/active/decommissioned), justification |
| **InfrastructureBinding** | Maps intent to specific infrastructure | binding_type (firewall_rule/route_policy/acl/load_balancer) |
| **FirewallRuleSet** | Device-level configuration | rule_name, action, source/destination_network, service_ports |

## Data Lineage Queries

**Forward (provision):** ApplicationService -> ServiceEndpoint -> ConnectivityIntent -> InfrastructureBinding -> FirewallRuleSet -> Device Config

**Reverse (audit):** Device Rule -> FirewallRuleSet -> InfrastructureBinding -> ConnectivityIntent -> ServiceEndpoint -> ApplicationService -> Business Owner

Given any firewall rule on any device, you can trace it back to the business owner who requested it.

## Operational Intent (3 Objects)

| Schema Object | Purpose | Key Attributes |
|---------------|---------|----------------|
| **OperationalOverride** | Time-bounded deviation from as-built intent | override_type (admin_shutdown/maintenance_mode/traffic_drain/emergency_bypass), status |
| **OverrideWindow** | Time bounds for the override | start_time, end_time, auto_revert (Boolean), extension_count |
| **OverrideAction** | Specific config change applied | action_type, target_object, original_state (JSON), override_state (JSON) |

## Override Workflow (Temporal)

1. `capture_current_state` — gNMI GET, store in OverrideAction.original_state
2. `apply_override` — gNMI SET with override config
3. `update_infrahub_status` — Mark override "active"
4. `wait_for_expiry_or_signal` — Temporal timer until end_time (interruptible)
5. `check_reversion_safety` — Validate circuits up, no conflicts
6. `revert_to_original` — gNMI SET to restore original_state
7. `mark_completed` — Update status to "reverted"

## Override-Aware Drift Detection

When drift is detected on a device with an active OperationalOverride:
- Expected state = override state (NOT as-built state)
- Query: "Is the device in the state its active override says it should be?"
- Implemented as an Infrahub check before flagging drift

## Compliance Metrics

- `intent_lineage_completeness_ratio` — % of device rules traceable to business intent
- `intent_orphaned_rules_count` — Rules with no active ConnectivityIntent (compliance risk)
- `override_auto_revert_success_total` — Should be 100%

## Common Mistakes

- Creating firewall rules without ConnectivityIntent lineage (orphaned rules)
- Not checking for active overrides before flagging drift
- Missing the reverse lineage path (audit queries need this)
- Not setting override end_time (overrides should always be time-bounded)
