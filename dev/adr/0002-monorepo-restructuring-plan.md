# Infrahub-Style Monorepo Restructuring Plan

## Overview

Restructure `project-network-synapse-3` into a professional monorepo following Infrahub (opsmill/infrahub) patterns. This transforms the current flat Python project into a `uv` workspace with two packages, unified tooling, AI-first developer documentation, and production-grade CI/CD.

---

## Phase 1: Directory Structure & File Moves

### 1.1 Create new directories

```
backend/network_synapse/          # Main package (renamed from infrahub/ + scripts/ + templates/)
backend/network_synapse/data/
backend/network_synapse/schemas/
backend/network_synapse/scripts/
backend/network_synapse/templates/
workers/synapse_workers/          # Workers package (renamed from temporal_workers/)
workers/synapse_workers/activities/
workers/synapse_workers/workflows/
development/                      # Docker Compose + Dockerfile (replaces docker/)
tasks/                            # Invoke task runner
changelog/                        # Towncrier fragments
dev/adr/
dev/commands/
dev/guidelines/
dev/guides/backend/
dev/guides/workers/
dev/knowledge/backend/
dev/knowledge/workers/
dev/prompts/
dev/skills/
.github/ISSUE_TEMPLATE/
```

### 1.2 Move existing files

| From | To |
|------|----|
| `infrahub/__init__.py` | `backend/network_synapse/__init__.py` |
| `infrahub/data/populate_sot.py` | `backend/network_synapse/data/populate_sot.py` |
| `infrahub/data/seed_data.yml` | `backend/network_synapse/data/seed_data.yml` |
| `infrahub/data/__init__.py` | `backend/network_synapse/data/__init__.py` |
| `infrahub/schemas/load_schemas.py` | `backend/network_synapse/schemas/load_schemas.py` |
| `infrahub/schemas/*.yml` | `backend/network_synapse/schemas/*.yml` |
| `infrahub/schemas/__init__.py` | `backend/network_synapse/schemas/__init__.py` |
| `scripts/__init__.py` | `backend/network_synapse/scripts/__init__.py` |
| `scripts/generate_configs.py` | `backend/network_synapse/scripts/generate_configs.py` |
| `scripts/deploy_configs.py` | `backend/network_synapse/scripts/deploy_configs.py` |
| `scripts/validate_configs.py` | `backend/network_synapse/scripts/validate_configs.py` |
| `templates/srlinux_bgp.j2` | `backend/network_synapse/templates/srlinux_bgp.j2` |
| `templates/srlinux_interfaces.j2` | `backend/network_synapse/templates/srlinux_interfaces.j2` |
| `temporal_workers/__init__.py` | `workers/synapse_workers/__init__.py` |
| `temporal_workers/worker.py` | `workers/synapse_workers/worker.py` |
| `temporal_workers/activities/*.py` | `workers/synapse_workers/activities/*.py` |
| `temporal_workers/workflows/*.py` | `workers/synapse_workers/workflows/*.py` |
| `docker/Dockerfile.temporal-worker` | `development/Dockerfile` |

### 1.3 Fix internal references

- `populate_sot.py`: Update seed file path from `infrahub/data/seed_data.yml` to `backend/network_synapse/data/seed_data.yml`
- `load_schemas.py`: Update `SCHEMA_LOAD_ORDER` paths from `infrahub/schemas/` to `backend/network_synapse/schemas/`
- `generate_configs.py`: Update `TEMPLATE_DIR` to point to new templates location
- `worker.py`: Module path changes from `temporal_workers.worker` to `synapse_workers.worker`
- `Dockerfile`: Update to use `uv sync` instead of `pip install -r requirements.txt`

### 1.4 Delete old files/dirs

- `requirements.txt` (replaced by pyproject.toml dependencies)
- `requirements-dev.txt` (replaced by dependency groups)
- `.pylintrc` (replaced by ruff in pyproject.toml)
- `mypy.ini` (merged into pyproject.toml)
- `pytest.ini` (merged into pyproject.toml)
- `main.py` (trivial stub)
- `new_file`, `new_file.yml` (artifacts)
- Empty `infrahub/`, `scripts/`, `templates/`, `temporal_workers/`, `docker/` dirs (after moving)

---

## Phase 2: Python Workspace Configuration

### 2.1 Root `pyproject.toml` (workspace orchestrator)

- Package name: `network-synapse`
- Build system: hatchling
- uv workspace linking `backend/` and `workers/`
- ALL tool configs consolidated:
  - **ruff**: line-length=120, target=py311, select=ALL with sensible ignores (replaces black + isort + pylint)
  - **mypy**: python_version=3.11, strict mode
  - **pytest**: testpaths, markers (unit, integration, slow), asyncio_mode=auto, timeout=300
  - **coverage**: source paths, omit patterns
  - **towncrier**: changelog fragment config
- Dependency groups: `testing`, `linting`, `typing`, `docs`

### 2.2 `backend/pyproject.toml`

- Package: `network-synapse` v0.1.0
- Python >= 3.11
- Runtime dependencies from current `requirements.txt`: infrahub-sdk, temporalio, nornir, jinja2, pydantic, httpx, pyyaml, pygnmi, grpcio
- CLI entry point: `synapse = "network_synapse.cli:app"` (future)

### 2.3 `workers/pyproject.toml`

- Package: `network-synapse-workers` v0.1.0
- Python >= 3.11
- Dependencies: temporalio, pydantic, httpx
- Depends on: `network-synapse` (workspace reference)

---

## Phase 3: Code Quality Tooling

### 3.1 Update `.pre-commit-config.yaml`

**Replace** black + isort hooks with ruff:
```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: check-ast
      - id: check-case-conflict
      - id: check-merge-conflict
      - id: check-toml
      - id: check-yaml
        args: [--allow-multiple-documents]
      - id: check-json
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: end-of-file-fixer
      - id: no-commit-to-branch
        args: [--branch, main]

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.12
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: [--baseline, .secrets.baseline]
        exclude: (library/.*|\.venv/.*|uv\.lock)

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
```

### 3.2 Create `.editorconfig`

UTF-8, LF line endings, 4-space indent for Python, 2-space for YAML/JSON/MD, trim trailing whitespace.

### 3.3 Create `.yamllint.yml`

120 char line length, relaxed rules, exclude .git, .venv, library/, node_modules.

### 3.4 Create `.markdownlint-cli2.yaml`

Disable line-length (MD013), allow duplicate headings in siblings, exclude changelog/.

---

## Phase 4: Invoke Task System (`tasks/`)

Create Python Invoke task modules:

- `tasks/__init__.py` - Register all task collections
- `tasks/main.py` - Root tasks: `format`, `lint`, `scan`, `check-all`
- `tasks/backend.py` - Backend: `test-unit`, `test-integration`, `generate-configs`, `load-schemas`, `seed-data`
- `tasks/workers.py` - Workers: `start-worker`, `test-workers`
- `tasks/dev.py` - Dev: `build`, `start`, `stop`, `destroy` (Docker)
- `tasks/docs.py` - Docs: `lint-docs`, `lint-yaml`, `lint-markdown`
- `tasks/shared.py` - Shared utilities (execute_command helper)

---

## Phase 5: AI Agent Developer Documentation (Context Nuggets)

### 5.1 Root files

- `AGENTS.md` - Comprehensive knowledge map: project architecture, directory layout, package descriptions, key commands, coding standards, contribution flow
- `CLAUDE.md` - Redirect: "See AGENTS.md for all project context"
- `.claude/commands` -> symlink to `../dev/commands`
- `.claude/skills` -> symlink to `../dev/skills`

### 5.2 `dev/` directory structure

- `dev/adr/0001-context-nuggets-pattern.md` - Documents why we use the Context Nuggets pattern
- `dev/adr/template.md` - ADR template
- `dev/commands/_shared.md` - Common instructions for all AI commands
- `dev/commands/fix-bug.md` - Bug-fixing workflow
- `dev/commands/guided-task.md` - General-purpose guided task
- `dev/guidelines/python.md` - Python coding standards (ruff, type hints, docstrings, import ordering)
- `dev/guidelines/git-workflow.md` - Branch strategy, commit conventions, PR process
- `dev/guidelines/changelog.md` - Towncrier changelog entry format
- `dev/guidelines/repository-organization.md` - Full directory guide
- `dev/knowledge/backend/architecture.md` - Backend architecture overview
- `dev/knowledge/workers/architecture.md` - Temporal workers architecture
- `dev/guides/backend/running-tests.md` - How to run backend tests
- `dev/guides/backend/adding-schemas.md` - How to add new Infrahub schemas
- `dev/guides/workers/adding-workflows.md` - How to add Temporal workflows

---

## Phase 6: GitHub Configuration

### 6.1 PR template (`.github/pull_request_template.md`)

Infrahub-style sections: Why, What changed, How to review, How to test, Impact & rollout, Checklist.

### 6.2 Issue templates (`.github/ISSUE_TEMPLATE/`)

- `bug_report.yml` - Bug report with environment, steps to reproduce, expected/actual behavior
- `feature_request.yml` - Feature request with use case, proposed solution
- `task.yml` - Task/chore with acceptance criteria

### 6.3 `CODEOWNERS`

```
/backend/    @anton-tvrz
/workers/    @anton-tvrz
/docs/       @anton-tvrz
/development/ @anton-tvrz
```

### 6.4 `dependabot.yml`

Weekly GitHub Actions dependency updates.

### 6.5 `file-filters.yml`

Path-based change detection: backend, workers, docs, ci, containerlab categories.

### 6.6 `labeler.yml`

Auto-label PRs based on changed paths (backend, workers, docs, ci, infrastructure).

---

## Phase 7: CI/CD Workflow Updates

Update both `pr-validation.yml` and `ci.yml`:
- Replace `pip install -r requirements.txt -r requirements-dev.txt` with `uv sync --all-groups`
- Replace `black --check` + `isort --check` + `pylint` with `ruff check` + `ruff format --check`
- Add `yamllint` step
- Update bandit source paths: `scripts/` -> `backend/` and `temporal_workers/` -> `workers/`
- Update pytest coverage paths: `--cov=backend/network_synapse --cov=workers/synapse_workers`
- Add path-based job filtering using `file-filters.yml`
- Add `uv-lock-check` job to verify lock file is in sync
- Update `build-artifacts.yml` Dockerfile path: `docker/Dockerfile.temporal-worker` -> `development/Dockerfile`

---

## Phase 8: Community & Documentation Files

- `CONTRIBUTING.md` - How to contribute: setup, branching, PR process, coding standards
- `CODE_OF_CONDUCT.md` - Contributor Covenant v2.1
- `SECURITY.md` - Security vulnerability reporting policy
- `LICENSE` - Apache 2.0 (or MIT, based on preference)
- `README.md` - Full project README with badges, architecture diagram, quickstart, directory layout

---

## Phase 9: Development Infrastructure

### 9.1 `development/docker-compose.yml`

Full dev environment with YAML anchors:
- `infrahub-server` (Infrahub)
- `temporal` (Temporal server)
- `temporal-ui` (Temporal Web UI)
- `database` (Neo4j for Infrahub)
- `cache` (Redis)
- `synapse-worker` (our Temporal worker)

### 9.2 `development/docker-compose-deps.yml`

Infrastructure deps only (no app containers): Infrahub, Temporal, Neo4j, Redis.

### 9.3 `development/Dockerfile`

Multi-stage build using uv:
- Stage 1: Python 3.11-slim + uv + system deps
- Stage 2: Copy project, install deps with `uv sync --frozen`
- CMD: `python -m synapse_workers.worker`

---

## Phase 10: Changelog & Versioning

- `changelog/` directory with `.gitkeep`
- Towncrier config in `pyproject.toml`:
  - Fragment types: added, changed, deprecated, removed, fixed, security
  - Template for CHANGELOG.md generation
- `CHANGELOG.md` initialized with v0.1.0 entry

---

## Phase 11: Finalization

1. Update `.gitignore` for new structure
2. Update `.python-version` to `3.11`
3. Run `uv sync --all-groups` to build lock file
4. Run `ruff check --fix .` to auto-format everything to new standards
5. Run `ruff format .` for consistent formatting
6. Run `pytest tests/` to verify tests still pass
7. Verify pre-commit hooks work: `pre-commit run --all-files`

---

## Final Directory Structure

```
project-network-synapse-3/
├── .claude/
│   ├── commands -> ../dev/commands
│   └── skills -> ../dev/skills
├── .editorconfig
├── .env.example
├── .github/
│   ├── CODEOWNERS
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml
│   │   ├── feature_request.yml
│   │   └── task.yml
│   ├── dependabot.yml
│   ├── file-filters.yml
│   ├── labeler.yml
│   ├── pull_request_template.md
│   └── workflows/
│       ├── build-artifacts.yml
│       ├── ci.yml
│       ├── deploy.yml
│       └── pr-validation.yml
├── .gitignore
├── .gitleaks.toml
├── .gitmodules
├── .markdownlint-cli2.yaml
├── .pre-commit-config.yaml
├── .secrets.baseline
├── .yamllint.yml
├── AGENTS.md
├── CHANGELOG.md
├── CLAUDE.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── SECURITY.md
├── pyproject.toml
├── uv.lock
│
├── ansible/
│   ├── inventory/
│   └── playbooks/
├── backend/
│   ├── pyproject.toml
│   └── network_synapse/
│       ├── __init__.py
│       ├── data/
│       │   ├── __init__.py
│       │   ├── populate_sot.py
│       │   └── seed_data.yml
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── bgp_session.yml
│       │   ├── load_schemas.py
│       │   ├── network_device.yml
│       │   └── network_interface.yml
│       ├── scripts/
│       │   ├── __init__.py
│       │   ├── deploy_configs.py
│       │   ├── generate_configs.py
│       │   └── validate_configs.py
│       └── templates/
│           ├── srlinux_bgp.j2
│           └── srlinux_interfaces.j2
├── changelog/
│   └── .gitkeep
├── containerlab/
│   └── topology.clab.yml
├── dev/
│   ├── adr/
│   │   ├── 0001-context-nuggets-pattern.md
│   │   └── template.md
│   ├── commands/
│   │   ├── _shared.md
│   │   ├── fix-bug.md
│   │   └── guided-task.md
│   ├── guidelines/
│   │   ├── changelog.md
│   │   ├── git-workflow.md
│   │   ├── python.md
│   │   └── repository-organization.md
│   ├── guides/
│   │   ├── backend/
│   │   │   ├── adding-schemas.md
│   │   │   └── running-tests.md
│   │   └── workers/
│   │       └── adding-workflows.md
│   ├── knowledge/
│   │   ├── backend/
│   │   │   └── architecture.md
│   │   └── workers/
│   │       └── architecture.md
│   ├── prompts/
│   │   └── .gitkeep
│   └── skills/
│       └── .gitkeep
├── development/
│   ├── Dockerfile
│   ├── docker-compose-deps.yml
│   └── docker-compose.yml
├── docs/
│   ├── infrastructure.md
│   ├── schemas.md
│   └── seed-data.md
├── library/
│   └── schema-library/  (git submodule)
├── tasks/
│   ├── __init__.py
│   ├── backend.py
│   ├── dev.py
│   ├── docs.py
│   ├── main.py
│   ├── shared.py
│   └── workers.py
└── tests/
    ├── conftest.py
    ├── integration/
    │   ├── __init__.py
    │   └── test_placeholder.py
    └── unit/
        ├── __init__.py
        └── test_placeholder.py
```

---

## Execution Estimate

~60+ files to create/modify across 11 phases. Implementation order follows dependency chain: structure first, then configs, then tooling, then docs, then CI.
