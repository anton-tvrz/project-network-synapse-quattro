# Repository Organization

## Top-Level Structure

| Directory       | Purpose                                                                                                                                                          |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/`      | Main Python package (`network-synapse`). Infrahub SoT interaction, config generation, schema management.                                                         |
| `workers/`      | Temporal workers package (`network-synapse-workers`). Durable workflow orchestration.                                                                            |
| `tests/`        | Test suite. `unit/` for fast isolated tests, `integration/` for tests requiring external services.                                                               |
| `ansible/`      | Ansible playbooks and inventory for network automation.                                                                                                          |
| `containerlab/` | Containerlab topology definition for the Nokia SR Linux spine-leaf lab.                                                                                          |
| `development/`  | Docker Compose files and Dockerfile for development infrastructure.                                                                                              |
| `docs/`         | Project documentation (markdown). Infrastructure guides, schema docs, seed data reference.                                                                       |
| `library/`      | Git submodule linking to `opsmill/schema-library` for Infrahub schema extensions.                                                                                |
| `tasks/`        | Python Invoke task modules. Unified CLI for development commands.                                                                                                |
| `changelog/`    | Towncrier changelog fragment files.                                                                                                                              |
| `dev/`          | Developer documentation following the Context Nuggets pattern.                                                                                                   |
| `.github/`      | GitHub Actions workflows, PR/issue templates, CODEOWNERS, labeler. See [issue-management.md](../guidelines/issue-management.md) for issue lifecycle conventions. |

## Config Files at Root

| File                      | Purpose                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------ |
| `pyproject.toml`          | Root workspace config: uv workspace, ruff, mypy, pytest, coverage, towncrier, bandit       |
| `.pre-commit-config.yaml` | Pre-commit hooks: ruff, trailing-whitespace, detect-secrets, gitleaks                      |
| `.editorconfig`           | Editor settings: charset, indent, line endings                                             |
| `.yamllint.yml`           | YAML linting rules                                                                         |
| `.markdownlint-cli2.yaml` | Markdown linting rules                                                                     |
| `.gitleaks.toml`          | Gitleaks secrets scanning config                                                           |
| `.secrets.baseline`       | Detect-secrets baseline                                                                    |
| `.coderabbit.yaml`        | CodeRabbit AI code review configuration (path-specific instructions, auto-review settings) |
| `uv.lock`                 | uv dependency lock file                                                                    |

## Package Structure

### `backend/network_synapse/`

```
network_synapse/
├── __init__.py
├── data/
│   ├── populate_sot.py     # Seeds Infrahub via GraphQL (idempotent upserts)
│   └── seed_data.yml       # Topology inventory: 3 devices, 11 interfaces, 4 BGP sessions
├── schemas/
│   ├── load_schemas.py     # POSTs schemas to Infrahub /api/schema/load
│   ├── network_device.yml  # DcimDevice extension: management_ip, lab_node_name, asn
│   ├── network_interface.yml # InterfacePhysical extension: role
│   └── bgp_session.yml     # Documentation reference (uses schema-library)
├── scripts/
│   ├── generate_configs.py # Jinja2 template renderer (implemented)
│   ├── deploy_configs.py   # gNMI push (stub)
│   └── validate_configs.py # gNMI GET validation (stub)
└── templates/
    ├── srlinux_bgp.j2      # SR Linux BGP JSON config (gNMI-ready)
    └── srlinux_interfaces.j2 # SR Linux interfaces JSON config
```

### `workers/synapse_workers/`

```
synapse_workers/
├── __init__.py
├── worker.py               # Temporal worker entry point
├── activities/
│   ├── config_deployment_activities.py  # deploy_config, rollback_config (stubs)
│   ├── device_backup_activities.py      # backup_running_config, store_backup (stubs)
│   ├── infrahub_activities.py           # fetch_device_config, update_device_status (stubs)
│   └── validation_activities.py         # validate_bgp, validate_interfaces (stubs)
└── workflows/
    ├── network_change_workflow.py       # NetworkChangeWorkflow (stub)
    ├── drift_remediation_workflow.py    # DriftRemediationWorkflow (stub)
    └── emergency_change_workflow.py     # EmergencyChangeWorkflow (stub)
```

## Dev Documentation (dev/)

Follows the Context Nuggets pattern (see ADR-0001):

| Directory         | Content                                                       | Primary Audience |
| ----------------- | ------------------------------------------------------------- | ---------------- |
| `dev/adr/`        | Architecture Decision Records                                 | Human + AI       |
| `dev/commands/`   | AI agent command workflows (symlinked to `.claude/commands`)  | AI agents        |
| `dev/guidelines/` | Coding standards: Python, Git, changelog, repo org            | Human + AI       |
| `dev/guides/`     | Step-by-step: running tests, adding schemas, adding workflows | Human + AI       |
| `dev/knowledge/`  | Architecture docs: backend, workers                           | Human + AI       |
| `dev/prompts/`    | Prompt templates for thinking tasks                           | Human            |
| `dev/skills/`     | AI agent skills (symlinked to `.claude/skills`)               | AI agents        |
