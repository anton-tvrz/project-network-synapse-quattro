# ADR-0004: Test-Driven Development as Default Methodology

## Status

Accepted

## Context

Network automation platforms must be trusted by operations teams before adoption. Trust requires proof that changes are safe, reversible, and tested. Untested automation is more dangerous than manual changes because it operates at scale — a bug in a template affects every device, not just one.

## Decision

All new features in NSQuattro follow TDD: write a failing test, implement the minimum code to pass, refactor. Tests are not optional, not deferred, and not written after implementation. CI pipelines enforce this by requiring test coverage gates before merge.

### The TDD Cycle in Network Automation

| Phase | TDD Action | Example |
|-------|-----------|---------|
| **RED** | Write a failing test defining expected behaviour | Test: "When a ConnectivityIntent is approved, a FirewallRuleSet is created with correct source, destination, and ports." — fails because workflow doesn't exist yet. |
| **GREEN** | Write minimum code to make the test pass | Implement ConnectivityProvisioningWorkflow with just enough logic. No optimisation, no edge cases. |
| **REFACTOR** | Improve code while keeping tests green | Extract intent-to-binding mapping, add type hints, simplify GraphQL query. |

### Test Types by Component

| Component | Test Type | What It Proves |
|-----------|----------|---------------|
| Infrahub schemas | Unit | Schema YAML structure, load ordering, dependency resolution |
| Seed data | Unit | YAML validity, idempotent upsert logic |
| Config generation | Unit + Golden file | Jinja2 output matches expected SR Linux JSON |
| gNMI deployment | Integration | Device accepts config, post-deploy state matches intent |
| Infrahub checks | Unit | Check logic with mock data (orphaned rules, IP conflicts) |
| Temporal workflows | Unit (WorkflowEnvironment) | Step ordering, saga compensation, signal handling |
| Temporal activities | Unit | Input/output contracts with mocked dependencies |
| Metrics | Unit | Correct labels and values emitted |

### Coverage Requirements

- Minimum 80% line coverage on new code
- CI blocks merge if coverage threshold not met
- Tests run BEFORE lint/format in pipeline (correctness first, aesthetics second)

## Consequences

- Slower initial development velocity
- Higher long-term reliability
- Every merged PR includes tests proving the feature works
- Rollback confidence increases because test suite validates both deploy and revert paths
