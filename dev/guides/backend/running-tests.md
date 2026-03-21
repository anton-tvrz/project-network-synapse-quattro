# Running Tests

## Quick Start

```bash
# Run unit tests only (fast, no external deps)
uv run invoke backend.test-unit

# Run integration tests (requires Infrahub + Temporal + Containerlab)
uv run invoke backend.test-integration

# Run all tests with coverage
uv run invoke backend.test-all
```

## Direct pytest Usage

```bash
# Run a specific test file
uv run pytest tests/unit/test_placeholder.py -v

# Run tests matching a pattern
uv run pytest tests/ -k "bgp" -v

# Run with parallel execution
uv run pytest tests/unit/ -n auto

# Run with verbose output and no capture
uv run pytest tests/unit/ -v -s
```

## Test Markers

| Marker | Description | Command |
|--------|-------------|---------|
| `@pytest.mark.unit` | Fast, isolated tests | `pytest -m unit` |
| `@pytest.mark.integration` | Requires running Infrahub | `pytest -m integration` |
| `@pytest.mark.live` | Requires Infrahub + Containerlab + gNMI | `pytest -m live` |
| `@pytest.mark.e2e` | Full pipeline tests | `pytest -m e2e` |
| `@pytest.mark.slow` | Tests taking >30 seconds | `pytest -m slow` |
| `@pytest.mark.pre_deployment` | Pre-deployment validation | `pytest -m pre_deployment` |
| `@pytest.mark.post_deployment` | Post-deployment validation | `pytest -m post_deployment` |

## Integration Tests (Infrahub)

Integration tests require a running Infrahub instance. The easiest way is via the CI Docker Compose:

```bash
# Start Infrahub (minimal CI stack)
docker compose -f development/docker-compose-ci.yml up -d

# Wait for Infrahub to be healthy
curl -sf http://localhost:8000/api/schema/summary

# Run integration tests
INFRAHUB_URL=http://localhost:8000 uv run pytest tests/integration/ -m integration -v

# Tear down
docker compose -f development/docker-compose-ci.yml down -v
```

### Integration Test Fixtures

Session-scoped fixtures in `tests/integration/conftest.py` handle:

- **`infrahub_url`** — From `INFRAHUB_URL` env var (default: `http://localhost:8000`)
- **`infrahub_client`** — Session-scoped `InfrahubConfigClient`
- **`resource_manager`** — Session-scoped `InfrahubResourceManager`
- **`load_schemas_once`** — Autouse fixture that loads schemas once per session
- **`seed_data_once`** — Autouse fixture that seeds data once per session

### Integration Test Files

| File | Tests |
|------|-------|
| `test_schema_loading.py` | Schema load, idempotency, API endpoint |
| `test_seed_data.py` | Object creation, relationships, idempotency |
| `test_resource_pools.py` | Pool creation, lookup, allocation |
| `test_transforms.py` | Transform execution via API, output validation |

## E2E Tests

E2E tests verify the complete pipeline and require all infrastructure:

```bash
INFRAHUB_URL=http://localhost:8000 uv run pytest tests/e2e/ -m e2e -v
```

## Writing Tests

1. Place unit tests in `tests/unit/test_<module>.py`
2. Place integration tests in `tests/integration/test_<module>.py`
3. Use fixtures from `tests/conftest.py` for shared test data
4. Mark tests with appropriate markers
5. Use `pytest-asyncio` for async tests (auto mode enabled)
6. For transforms: use `MagicMock()` for `client` and `infrahub_node` constructor args
7. For checks: instantiate directly — `InfrahubCheck()` needs no constructor args

## Coverage

Coverage is configured in `pyproject.toml [tool.coverage]`. Reports cover:
- `backend/network_synapse/`
- `workers/synapse_workers/`
