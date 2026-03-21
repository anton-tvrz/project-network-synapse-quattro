# Week 1 Walkthrough: Monorepo Restructuring & Tooling

Week 1 focused on transforming the flat Python project into a professional `uv` workspace monorepo, following the plan in [0002-monorepo-restructuring-plan.md](file:///Users/anton/PYPROJECTS/project-network-synapse-3/dev/adr/0002-monorepo-restructuring-plan.md).

---

## Changes Made

### Phase 1 — Directory Structure & File Moves

- Restructured from flat `infrahub/`, `scripts/`, `templates/`, `temporal_workers/` into two workspace packages:
  - **`backend/network_synapse/`** — main package (data, schemas, scripts, templates)
  - **`workers/synapse_workers/`** — Temporal worker package (activities, workflows)
- Moved Docker infrastructure to `development/`
- Moved Containerlab topology to `containerlab/`
- Fixed all internal import paths (`infrahub.` → `network_synapse.`, `temporal_workers.` → `synapse_workers.`)
- Deleted legacy files: `requirements.txt`, `requirements-dev.txt`, `.pylintrc`, `mypy.ini`, `pytest.ini`, `main.py`

### Phase 2 — Python Workspace Configuration

- Created root `pyproject.toml` as workspace orchestrator with `uv` workspace linking
- Created `backend/pyproject.toml` (package: `network-synapse`) with runtime dependencies
- Created `workers/pyproject.toml` (package: `network-synapse-workers`) with workspace dependency on backend
- Consolidated all tool configs into root `pyproject.toml`:
  - **Ruff**: line-length=120, target=py311, comprehensive rule selection
  - **MyPy**: strict mode, Python 3.11
  - **Pytest**: markers (unit, integration, slow), asyncio_mode=auto
  - **Coverage**: source paths, omit patterns
  - **Towncrier**: changelog fragment config
  - **Bandit**: security scanning exclusions

### Phase 3 — Code Quality Tooling

- Updated `.pre-commit-config.yaml` to use ruff (replacing black + isort + pylint)
- Created `.editorconfig` (UTF-8, LF endings, 4-space Python indent)
- Created `.yamllint.yml` (120 char limit, relaxed rules)
- Created `.markdownlint-cli2.yaml` (disabled line-length for docs)
- Created `.secrets.baseline` for detect-secrets

### Phase 4 — Invoke Task System

Built the `tasks/` module with Python Invoke:

| Module             | Tasks                                                                            |
| ------------------ | -------------------------------------------------------------------------------- |
| `tasks/main.py`    | `format`, `lint`, `scan`, `check-all`                                            |
| `tasks/backend.py` | `test-unit`, `test-integration`, `generate-configs`, `load-schemas`, `seed-data` |
| `tasks/workers.py` | `start-worker`, `test-workers`                                                   |
| `tasks/dev.py`     | `build`, `start`, `stop`, `destroy` (Docker)                                     |
| `tasks/docs.py`    | `lint-docs`, `lint-yaml`, `lint-markdown`                                        |
| `tasks/shared.py`  | `execute_command` helper                                                         |

---

## Verification

- `uv sync --all-groups` — lock file built successfully
- `uv run ruff check .` — zero lint errors
- `uv run ruff format .` — all files formatted
- `uv run invoke check-all` — full pipeline green
- `pre-commit run --all-files` — all hooks passing
