# Network Synapse Quattro — Agent Knowledge Map

> This file is the entry point for AI coding agents working on this project.
> It provides a comprehensive map of the codebase, conventions, and development workflow.

## What Is This Project?

**Network Synapse Quattro** is a network automation platform for managing Nokia SR Linux datacenter fabric switches. It automates the full lifecycle of network configuration changes against a spine-leaf lab topology using:

- **Infrahub** (OpsMill) — Graph-based Source of Truth (SoT) for network inventory, schemas, and intended state
- **Temporal** — Durable workflow orchestration engine for auditable automation workflows
- **Containerlab** — Nokia SR Linux virtual network labs running locally via Docker/OrbStack

**Pipeline:** Query Infrahub SoT -> Render Jinja2 config templates -> Deploy via gNMI to SR Linux -> Validate post-deploy state

**Deployment model:** All workloads run locally via Docker Compose + OrbStack on Apple Silicon. No cloud VMs.

## Repository Structure

```
project-network-synapse-quattro/
├── backend/                    # Python package: network-synapse-quattro
│   ├── pyproject.toml
│   └── network_synapse/
│       ├── data/               # Infrahub SoT data seeding (populate_sot.py, seed_data.yml)
│       ├── schemas/            # Infrahub schema extensions (load_schemas.py, *.yml)
│       ├── scripts/            # Automation scripts (generate/deploy/validate configs)
│       └── templates/          # Jinja2 templates for Nokia SR Linux (gNMI-ready JSON)
│
├── workers/                    # Python package: network-synapse-quattro-workers
│   ├── pyproject.toml
│   └── synapse_workers/
│       ├── worker.py           # Temporal worker entry point
│       ├── activities/         # Temporal activity definitions
│       └── workflows/          # Temporal workflow definitions
│
├── tests/                      # Test suite (unit + integration)
│   ├── conftest.py             # Shared fixtures (spine-leaf topology, BGP sessions)
│   ├── unit/
│   └── integration/
│
├── containerlab/               # Containerlab topology definition (spine-leaf lab)
├── development/                # Docker Compose, Dockerfile for dev environment
├── docs/                       # Project documentation (markdown)
├── library/                    # Git submodule: opsmill/schema-library
├── tasks/                      # Invoke task runner modules
├── changelog/                  # Towncrier changelog fragments
│
├── dev/                        # Developer documentation (Context Nuggets)
│   ├── adr/                    # Architecture Decision Records
│   ├── commands/               # Reusable AI agent commands
│   ├── guidelines/             # Coding standards and conventions
│   ├── guides/                 # Step-by-step procedures
│   ├── knowledge/              # Architecture explanations
│   ├── prompts/                # Prompt templates
│   └── skills/                 # AI agent skills
│
├── pyproject.toml              # Root workspace config (uv + all tool configs)
├── .pre-commit-config.yaml     # Pre-commit hooks (ruff, detect-secrets, gitleaks)
└── .github/                    # CI/CD workflows, PR/issue templates, CODEOWNERS
```

## Workspace Architecture

This is a **uv workspace monorepo** with two packages:

| Package                           | Import Path       | Description                                                         |
| --------------------------------- | ----------------- | ------------------------------------------------------------------- |
| `network-synapse-quattro`         | `network_synapse` | Backend: Infrahub interaction, config generation, schema management |
| `network-synapse-quattro-workers` | `synapse_workers` | Temporal workers: durable workflows, activities                     |

Workers depend on the backend package. Both are linked via `[tool.uv.sources]` in the root `pyproject.toml`.

## Key Commands

```bash
# Setup
uv sync --all-groups                    # Install all dependencies

# Development
uv run invoke format                    # Format code (ruff)
uv run invoke lint                      # Lint code (ruff)
uv run invoke scan                      # Security scan (bandit + detect-secrets)
uv run invoke check-all                 # All quality checks

# Testing
uv run invoke backend.test-unit         # Unit tests
uv run invoke backend.test-integration  # Integration tests
uv run invoke backend.test-all          # All tests

# Backend operations
uv run invoke backend.load-schemas      # Load schemas into Infrahub
uv run invoke backend.seed-data         # Seed data into Infrahub
uv run invoke backend.typecheck         # MyPy type checking

# Workers
uv run invoke workers.start             # Start Temporal worker

# Infrastructure
uv run invoke dev.deps                  # Start infrastructure dependencies
uv run invoke dev.deps-stop             # Stop infrastructure dependencies
uv run invoke dev.build                 # Build Docker images
uv run invoke dev.lab-deploy            # Deploy Containerlab topology
uv run invoke dev.lab-destroy           # Destroy Containerlab topology

# Documentation
uv run invoke docs.lint-yaml            # Lint YAML files
```

## Coding Standards

- **Formatter/Linter:** Ruff (replaces black, isort, pylint, flake8)
- **Line length:** 120 characters
- **Python version:** 3.12+
- **Type hints:** Required on all public functions; `ignore_missing_imports = true` in mypy
- **Import order:** stdlib -> third-party -> first-party (`network_synapse`, `synapse_workers`)
- **Docstrings:** Required on all modules, classes, and public functions
- **Quote style:** Double quotes
- **Line endings:** LF (Unix)

See `dev/guidelines/python.md` for full details.

## Git Workflow

- **`main`** — Protected, production-ready code. No direct commits.
- **Feature branches:** `feature/<description>` from `main`
- **Bug fixes:** `fix/<description>` from `main`
- **Infrastructure:** `dev/<description>` from `main`
- **Commit style:** Conventional Commits (`feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `test:`, `chore:`)

See `dev/guidelines/git-workflow.md` for full details.

## Agent Rules (MANDATORY)

> **All AI agents MUST follow these rules when working on this project.**

### Workflow for Code Changes

```
git checkout main && git pull origin main   # ALWAYS start from latest main
git checkout -b feat/<description> main
# ... make changes ...
uv run invoke check-all               # MUST pass
git add -A && git commit -m "feat: ..."  # Conventional Commits
git push -u origin feat/<description>
gh pr create --base main               # Open PR — ALWAYS use --base main
# PR body MUST include "Closes #<issue-number>" — CI will reject PRs without it
# → CI validates → Review → Merge
```

> **Git hooks enforce these rules locally.** Pre-commit blocks commits to `main`.
> Pre-push blocks pushes to `main`. See `.githooks/` and `.pre-commit-config.yaml`.

### Prohibited Actions

- Direct `git push` to `main`
- Editing files on remote infrastructure that exist in the repo

## Changelog

Uses Towncrier for changelog management. When making changes, add a fragment file:

```bash
# Format: changelog/<issue-number>.<type>.md
# Types: added, changed, deprecated, removed, fixed, security
echo "Added BGP session validation workflow" > changelog/42.added.md
```

CI enforces that every PR includes a changelog fragment. For PRs that don't need one (CI-only, docs-only, test-only, internal refactoring), add the `skip-changelog` label to skip the check.

See `dev/guidelines/changelog.md` for details.

## CI/CD Pipeline Architecture

### Workflow Files

| File | Purpose | Trigger |
|------|---------|---------|
| `quality.yml` | Reusable quality checks (lint, security, tests) | Called by other workflows (`workflow_call`) |
| `pr-validation.yml` | PR gates: quality + issue link + changelog + labeler | `pull_request` to main |
| `release.yml` | Version management: changelog + tag + GitHub Release | Manual dispatch |
| `build-artifacts.yml` | Docker images + Python packages | Tag push `v*` |
| `issue-automation.yml` | Bug triage + issue close guard | Issue opened/closed |

### Invoke Tasks to CI Job Mapping

| Invoke Task | CI Job | Workflow |
|-------------|--------|----------|
| `invoke lint` | `code-quality` | quality.yml |
| `invoke scan` | `security-scanning` | quality.yml |
| `invoke check-all` | `code-quality` + `security-scanning` | quality.yml |
| `invoke backend.test-unit` | `unit-tests` | quality.yml |
| `invoke backend.test-integration` | `integration-hygiene` | quality.yml (when enabled) |
| `invoke docs.lint-yaml` | `yaml-lint` | quality.yml |
| `invoke backend.typecheck` | Part of `code-quality` (mypy step) | quality.yml |

### How to Modify CI

1. **Quality checks** (lint, test, security): Edit `quality.yml` — changes propagate to PR pipeline
2. **PR-specific gates** (issue link, changelog): Edit `pr-validation.yml`
3. **Path filters** (which jobs run for which files): Edit `.github/file-filters.yml`
4. **Auto-labels**: Edit `.github/labeler.yml`

### Environment Secrets

| Secret | Used By | Scope |
|--------|---------|-------|
| `CODECOV_TOKEN` | quality.yml | Repository-level |
| `RELEASE_PAT` | release.yml | Repository-level |

See `dev/knowledge/cicd-architecture.md` Section 9 for the full engineering playbook.

## Developer Documentation (dev/)

This project follows the **Context Nuggets** pattern (ADR-0001) for developer documentation:

| Directory         | Purpose                                                                                                               | Audience   |
| ----------------- | --------------------------------------------------------------------------------------------------------------------- | ---------- |
| `dev/adr/`        | Architecture Decision Records                                                                                         | Human + AI |
| `dev/commands/`   | Reusable AI agent commands                                                                                            | AI agents  |
| `dev/guidelines/` | Coding standards and conventions                                                                                      | Human + AI |
| `dev/guides/`     | Step-by-step procedures and best practices (including [PR best practices](dev/guides/pull-request-best-practices.md)) | Human + AI |
| `dev/knowledge/`  | Architecture explanations                                                                                             | Human + AI |
| `dev/prompts/`    | Prompt templates for thinking tasks                                                                                   | Human      |
| `dev/skills/`     | Domain-specific AI agent skills                                                                                       | AI agents  |

## Infrastructure

All services run locally via Docker Compose + OrbStack. `uv run invoke dev.deps` starts
12 containers (~10GB total memory reserved):

- **Infrahub stack (7):** neo4j, redis, rabbitmq, task-manager-db (postgres), task-manager, infrahub-server, task-worker
- **Temporal stack (3):** postgres, temporal, temporal-ui
- **Observability (2):** prometheus, grafana

Infrahub takes 60-90s to fully initialize (Neo4j + task-manager must be ready first).
The default admin API token (`06438eb2-8019-4776-878c-0941b1f1d1ec`) is pre-configured in `.env.example`.
SuzieQ is commented out (broken on Apple Silicon).

| Component          | Local Port | Description                |
| ------------------ | ---------- | -------------------------- |
| Infrahub           | 8000       | Web UI + GraphQL API       |
| Task Manager       | 4200       | Prefect API                |
| Temporal           | 7233       | gRPC endpoint              |
| Temporal UI        | 8080       | Web dashboard              |
| Grafana            | 3000       | Dashboards                 |
| Prometheus         | 9090       | Metrics + alerts           |
| SR Linux (gNMI)    | 57400      | Per-device gNMI            |
| Containerlab Graph | 50080      | Topology visualization     |

## Lab Topology

3-node Nokia SR Linux spine-leaf fabric:

- `spine01` (IXR-D3, AS65000) — 4 fabric links
- `leaf01` (IXR-D2, AS65001) — 2 uplinks to spine
- `leaf02` (IXR-D2, AS65002) — 2 uplinks to spine
- Management: `172.20.20.0/24` (DHCP by Containerlab)
- Fabric underlay: `/31` point-to-point eBGP
