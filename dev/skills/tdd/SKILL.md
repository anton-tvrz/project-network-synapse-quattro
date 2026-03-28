# TDD — Test-Driven Development Skill

## Metadata
- name: tdd
- triggers: test, testing, TDD, pytest, coverage, red-green-refactor
- project: Network Synapse Quattro

## Core Principle

All new code follows TDD: write a failing test, implement the minimum to pass, refactor. Tests are not optional, not deferred, and not written after implementation.

## The TDD Cycle

| Phase | Action | Example |
|-------|--------|---------|
| **RED** | Write a failing test defining expected behaviour | `test_connectivity_intent_creates_firewall_ruleset()` — fails because workflow doesn't exist |
| **GREEN** | Write minimum code to make the test pass | Implement just enough logic. No optimisation, no edge cases |
| **REFACTOR** | Improve code while keeping tests green | Extract reusable functions, add type hints, simplify queries |

## Test File Naming Convention

| Source File | Test File |
|-------------|-----------|
| `backend/network_synapse/schemas/<name>.yml` | `tests/unit/test_<name>_schema.py` |
| `backend/network_synapse/checks/<name>.py` | `tests/unit/test_<name>_check.py` |
| `backend/network_synapse/scripts/<name>.py` | `tests/integration/test_<name>.py` |
| `workers/synapse_workers/workflows/<name>.py` | `tests/unit/test_<name>_workflow.py` |
| `workers/synapse_workers/activities/<name>.py` | `tests/unit/test_<name>_activities.py` |

## Pytest Fixture Patterns

Use shared fixtures from `tests/conftest.py`:
- `spine_leaf_topology` — 3-node topology (spine01, leaf01, leaf02)
- `bgp_sessions` — eBGP session data for all fabric links
- `infrahub_client` — Mocked Infrahub async client
- `temporal_env` — Temporal `WorkflowEnvironment` for unit testing workflows

## Coverage Requirements

- Minimum **80%** line coverage on new code
- CI gate: `coverage report --fail-under=80`
- Coverage report generated on every test run

## Golden File Testing (Jinja2 Templates)

For config generation templates:
1. Store expected output in `tests/golden/<template_name>.json`
2. Test renders template with known inputs
3. Compare output byte-for-byte against golden file
4. Any change causes test failure — developer must explicitly update the golden file
5. Golden file updates appear in PR diff for review

## Temporal Workflow Testing

Use `temporalio.testing.WorkflowEnvironment`:
- Unit test workflows without a running Temporal server
- Mock activities to test workflow logic in isolation
- Use time-skipping for timer-based workflows (e.g., OperationalOverrideWorkflow)
- Test saga compensation by making activities raise errors

## TDD Workflow Commands

```bash
# Step 1: Run new test (expect RED)
uv run pytest tests/unit/test_new_feature.py -x

# Step 2: Implement minimum code

# Step 3: Run test again (expect GREEN)
uv run pytest tests/unit/test_new_feature.py -x

# Step 4: Run full suite (expect all GREEN)
uv run invoke backend.test-all
```
