# Engineering Playbook

This file captures the development patterns, standards, and workflows used in this project. It serves as a blueprint for recreating this setup in a new project and as a reference for how decisions were made.

Organized by lifecycle stage: setup, development, CI/CD, documentation, release.

---

## 1. Philosophy & Principles

**Monorepo over polyrepo.** Related packages that depend on each other belong in a single repository, managed by a workspace tool. This eliminates cross-repo dependency coordination and keeps CI/CD unified.

**Configuration centralization.** All tool configuration lives in `pyproject.toml` wherever the tool supports it. One file to understand the full quality toolchain. Tools that require their own config files (yamllint, markdownlint, editorconfig) use dotfiles at the root.

**AI-first documentation.** Documentation is structured for both human developers and AI coding agents. Small, focused files organized by purpose (the "Context Nuggets" pattern from opsmill/infrahub) rather than monolithic documents. This keeps each file within AI context window limits and makes context task-specific.

**Security by default.** Use GitHub Advanced Security (CodeQL for code scanning, GitHub secret scanning, Dependabot for dependency vulnerabilities) as the primary security layer. This provides native GitHub integration, automatic PR annotations, and the Security tab for tracking findings. Ruff's `S` (bandit) rule category provides additional inline security linting.

**Automation over manual process.** Pre-commit hooks enforce standards locally, CI enforces them remotely, and a task runner provides a unified CLI. Developers should never need to remember exact tool commands.

**Clean git history.** Squash merge on PRs, conventional commits, branch protection preventing direct commits to main.

**Local-first development.** All workloads run locally via Docker Compose and OrbStack on Apple Silicon. No cloud VMs, no remote deployment pipelines. See [ADR-0003](../adr/0003-local-development-migration.md).

**Gradual typing.** Type hints are required on public functions but `disallow_untyped_defs = false` and `ignore_missing_imports = true` because third-party library stubs are incomplete. Strictness increases over time.

---

## 2. Project Scaffolding

### 2.1 Monorepo Architecture (uv Workspace)

The project uses a **uv workspace monorepo**. The root `pyproject.toml` is a virtual workspace root -- it has no `[build-system]` section and is not a distributable package itself. It declares the workspace members and links them as sources:

```toml
[tool.uv.workspace]
members = ["backend", "workers"]

[tool.uv.sources]
network-synapse-quattro = { workspace = true }
network-synapse-quattro-workers = { workspace = true }
```

Each package directory contains its own `pyproject.toml` with hatchling as build backend:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["<import_name>"]
```

**Why hatchling:** Fast, zero-config for standard layouts, and the recommended build backend for uv workspaces.

When one package depends on another, declare it in the dependent package's dependencies list. The workspace source linkage resolves it locally during development.

### 2.2 Directory Layout

```
<project>/
  backend/                    # Primary Python package
    pyproject.toml
    <import_name>/
      __init__.py
      data/                   # Data seeding scripts and seed files
      schemas/                # Schema definitions and loaders
      scripts/                # Automation scripts (generate/deploy/validate)
      templates/              # Jinja2 templates
      infrahub/               # External service client + models

  workers/                    # Secondary Python package (depends on backend)
    pyproject.toml
    <import_name>/
      __init__.py
      worker.py               # Worker entry point
      activities/             # Activity definitions (one file per domain)
      workflows/              # Workflow definitions (one file per workflow)

  tests/
    __init__.py
    conftest.py               # Shared fixtures
    unit/
    integration/

  tasks/                      # Invoke task runner modules
    __init__.py
    shared.py                 # Constants and utilities
    main.py                   # Root-level tasks (format, lint, scan)
    backend.py                # Backend tasks (test, generate, seed)
    workers.py                # Worker tasks (start, test)
    dev.py                    # Dev infrastructure tasks (docker, containerlab)
    docs.py                   # Documentation tasks (lint-yaml, lint-markdown)

  dev/                        # Developer documentation (Context Nuggets)
    adr/                      # Architecture Decision Records
    commands/                 # AI agent command workflows
    guidelines/               # Coding standards and conventions
    guides/                   # Step-by-step procedures
    knowledge/                # Architecture explanations
    prompts/                  # Prompt templates
    skills/                   # AI agent skills

  development/                # Docker Compose files + Dockerfile
  docs/                       # User-facing project documentation
  changelog/                  # Towncrier fragment files
  library/                    # Git submodules (external schemas)

  .github/
    workflows/                # CI/CD workflow files
    ISSUE_TEMPLATE/           # Issue form templates (YAML)
    file-filters.yml          # Path-based change detection
    labeler.yml               # PR auto-labeling rules
    CODEOWNERS                # Code ownership
    dependabot.yml            # Dependency automation
    pull_request_template.md  # PR template

  .claude/
    commands -> ../dev/commands   # Symlink for Claude Code
    skills -> ../dev/skills      # Symlink for Claude Code
```

### 2.3 Root Configuration Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Workspace config + all tool configs (ruff, mypy, pytest, coverage, towncrier) |
| `.pre-commit-config.yaml` | Pre-commit hooks (ruff, whitespace, ast checks) |
| `.editorconfig` | Editor settings (charset, indent, line endings) |
| `.yamllint.yml` | YAML linting rules |
| `.markdownlint-cli2.yaml` | Markdown linting rules |
| `.python-version` | Pin Python version for uv |
| `uv.lock` | Dependency lock file (checked into git, CI verifies sync) |

### 2.4 Python Version

`.python-version` contains `3.12`. Root `pyproject.toml` declares `requires-python = ">=3.12"`.

---

## 3. Package Management

### 3.1 uv as Package Manager

- Install all dependencies: `uv sync --all-groups`
- Install specific group only: `uv sync --group testing`
- All commands run via `uv run <command>` to use the project's virtual environment
- Lock file checked in; CI runs `uv lock --check` to verify sync

### 3.2 Dependency Groups

Defined in the root `pyproject.toml` as `[dependency-groups]`:

| Group | Contents | Purpose |
|-------|----------|---------|
| `testing` | pytest, pytest-cov, pytest-asyncio, pytest-timeout, pytest-xdist, pytest-httpx | Test suite |
| `linting` | ruff, yamllint | Lint tools |
| `typing` | mypy, type stubs (PyYAML, requests) | Type checking |
| `dev` | invoke, pre-commit, ipython, towncrier | Development tools |

**Why dependency groups (not extras):** These are development dependencies that should never be installed by package consumers. Groups are a uv-specific feature that replaces the old `[tool.poetry.dev-dependencies]` pattern.

### 3.3 Git Submodules

External schema libraries are included as git submodules under `library/`:

```bash
# After clone
git submodule update --init --recursive

# Update to latest
git submodule update --remote library/<name>
```

CI uses `submodules: true` on the checkout action.

---

## 4. Code Quality Toolchain

### 4.1 Ruff (replaces black, isort, pylint, flake8)

**Why:** Single tool for both linting and formatting, extremely fast (Rust-based), configured entirely in pyproject.toml.

```toml
[tool.ruff]
line-length = 120
target-version = "py312"
exclude = [".git", ".venv", "__pycache__", "library", "*.egg-info", "dist", "build"]
```

**Rule selection** (comprehensive):

```toml
select = [
    "F",    # pyflakes
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "I",    # isort
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "S",    # bandit (security)
    "B",    # bugbear
    "A",    # builtins
    "C4",   # comprehensions
    "DTZ",  # datetimez
    "T10",  # debugger
    "ISC",  # implicit-str-concat
    "ICN",  # import-conventions
    "PIE",  # misc
    "PT",   # pytest-style
    "RSE",  # raise
    "RET",  # return
    "SLF",  # private-access
    "SIM",  # simplify
    "TID",  # tidy-imports
    "TCH",  # type-checking
    "ARG",  # unused-arguments
    "PTH",  # pathlib
    "ERA",  # commented-out code
    "PL",   # pylint
    "RUF",  # ruff-specific
]
```

**Ignore list with rationale:**

| Rule | Why Ignored |
|------|-------------|
| `S101` | assert used -- fine in tests and assertions |
| `S603`, `S607` | subprocess calls -- needed for task runner |
| `PLR0913` | too many arguments -- common in data classes |
| `PLR2004` | magic value comparison -- too noisy |
| `ERA001` | commented-out code -- too noisy during active development |
| `ARG001`, `ARG002` | unused arguments -- common in stubs and fixtures |
| `RET504` | unnecessary assignment before return -- readability preference |
| `PLR0915` | too many statements -- needed for complex setup scripts |
| `S701` | jinja2 autoescape -- templates are trusted internal configs |

**Per-file ignores:**

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101", "S106", "PLR2004", "ARG001", "SLF001", "PT004", "PLC0415"]
"**/activities/*.py" = ["ARG001"]
"**/workflows/*.py" = ["ARG001"]
```

**Format settings:** double quotes, space indent, LF line endings.

**isort config:** `known-first-party = ["<package_a>", "<package_b>"]`

### 4.2 MyPy

```toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
check_untyped_defs = true
ignore_missing_imports = true
disallow_untyped_defs = false
exclude = ["library/", "\\.venv/", "build/", "dist/"]
```

**Why these settings:** `ignore_missing_imports` because many third-party libraries lack type stubs. `disallow_untyped_defs = false` for gradual adoption. MyPy runs in CI with `continue-on-error: true` during early project phases, becoming strict once coverage is sufficient.

### 4.3 GitHub Advanced Security

Instead of standalone tools (Bandit, Gitleaks, detect-secrets), use GitHub's native security features:

**CodeQL** -- Static analysis for code scanning:
- Enable via repository Settings > Security > Code scanning
- GitHub provides default CodeQL workflow or custom `.github/workflows/codeql.yml`
- Scans on PR and push, results appear in Security tab and as PR annotations
- Covers vulnerability patterns, injection risks, and security anti-patterns

**Secret Scanning** -- Detects committed secrets:
- Enable via Settings > Security > Secret scanning
- Push protection blocks commits containing known secret patterns
- Alerts appear in Security tab with remediation guidance
- Partners with 200+ service providers for token validation

**Dependabot Security Alerts** -- Dependency vulnerabilities:
- Enable via Settings > Security > Dependabot alerts
- Automatic PRs to update vulnerable dependencies
- Severity-based alerting

**Ruff S rules** -- Inline security linting (bandit rule set) provides fast local feedback during development, complementing GitHub's server-side scanning.

### 4.4 YAML Linting

```yaml
extends: default
rules:
  line-length: { max: 120 }
  comments: { min-spaces-from-content: 1 }
  comments-indentation: disable
  document-start: disable
  truthy: { allowed-values: ["true", "false", "on", "off", "yes", "no"] }
ignore: |
  .git/
  .venv/
  library/
  node_modules/
  *.lock
```

### 4.5 Markdown Linting

```yaml
config:
  MD013: false                        # No line length limit (URLs make this impractical)
  MD024: { siblings_only: true }      # Allow duplicate headings in sibling sections
  MD033: false                        # Allow inline HTML (badges, collapsible sections)
  MD034: false                        # Allow bare URLs
ignores:
  - ".venv/**"
  - "library/**"
  - "node_modules/**"
  - "changelog/**"
  - "CHANGELOG.md"
```

### 4.6 EditorConfig

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.py]
indent_size = 4

[*.{yml,yaml}]
indent_size = 2

[*.{json,toml}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false
indent_size = 2

[*.j2]
indent_size = 2

[Makefile]
indent_style = tab
```

---

## 5. Pre-commit Hooks

Install: `uv run pre-commit install`

Run all: `uv run pre-commit run --all-files`

| Repo | Hooks |
|------|-------|
| `pre-commit/pre-commit-hooks` | trailing-whitespace, check-ast, check-case-conflict, check-merge-conflict, check-toml, check-yaml (--allow-multiple-documents), check-json, check-added-large-files (--maxkb=500), end-of-file-fixer, no-commit-to-branch (--branch main) |
| `astral-sh/ruff-pre-commit` | ruff (--fix), ruff-format |

**Why `no-commit-to-branch --branch main`:** Prevents accidental direct commits to the production branch. All work must go through feature branches and PRs.

**Why ruff `--fix`:** Auto-corrects import sorting, unused imports, and simple style issues on every commit so developers don't need to manually fix lint errors.

Secrets detection is handled server-side by GitHub Advanced Security (secret scanning with push protection) rather than local pre-commit hooks.

---

## 6. Task Runner (Invoke)

### 6.1 Namespace Organization

`tasks/__init__.py` organizes tasks into namespaces:

```python
ns = Collection()
# Root-level tasks (no prefix needed)
ns.add_task(main.format_code, name="format")
ns.add_task(main.lint, name="lint")
ns.add_task(main.scan, name="scan")
ns.add_task(main.check_all, name="check-all")
# Sub-collections (prefixed: backend.test-unit, dev.start, etc.)
ns.add_collection(Collection.from_module(backend), name="backend")
ns.add_collection(Collection.from_module(workers), name="workers")
ns.add_collection(Collection.from_module(dev), name="dev")
ns.add_collection(Collection.from_module(docs), name="docs")
```

### 6.2 Shared Utilities

`tasks/shared.py` defines project-wide constants and a command executor:

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
WORKERS_DIR = PROJECT_ROOT / "workers"
TESTS_DIR = PROJECT_ROOT / "tests"

def execute_command(ctx, command, pty=True, warn=False, **kwargs):
    return ctx.run(command, pty=pty, warn=warn, **kwargs)
```

### 6.3 Full Task Registry

| Command | Description |
|---------|-------------|
| `uv run invoke format` | Ruff check --fix + ruff format |
| `uv run invoke lint` | Ruff check + format --check |
| `uv run invoke scan` | Security scan |
| `uv run invoke check-all` | lint + scan (pre-task chain) |
| `uv run invoke backend.test-unit` | pytest tests/unit/ with coverage |
| `uv run invoke backend.test-integration` | pytest tests/integration/ with timeout |
| `uv run invoke backend.test-all` | All tests with full coverage |
| `uv run invoke backend.typecheck` | MyPy on backend/ |
| `uv run invoke workers.start` | Start worker process |
| `uv run invoke workers.test` | Worker-specific tests |
| `uv run invoke dev.build` | Docker build |
| `uv run invoke dev.start` | Docker compose up |
| `uv run invoke dev.stop` | Docker compose down |
| `uv run invoke dev.deps` | Start infrastructure dependencies only |
| `uv run invoke dev.deps-stop` | Stop infrastructure dependencies |
| `uv run invoke dev.lab-deploy` | Deploy lab topology |
| `uv run invoke dev.lab-destroy` | Destroy lab topology |
| `uv run invoke docs.lint-yaml` | yamllint all YAML |
| `uv run invoke docs.lint-markdown` | markdownlint-cli2 |
| `uv run invoke docs.lint-all` | All documentation linters |

---

## 7. Git Workflow

### 7.1 Branch Strategy

| Branch | Purpose | Merges From |
|--------|---------|-------------|
| `main` | Production-ready. Protected, no direct commits. | Feature/fix branches via PR |

All feature work branches from `main` and merges back via Pull Request.

### 7.2 Branch Naming

| Pattern | Use Case | Example |
|---------|----------|---------|
| `feature/<description>` | New features | `feature/bgp-validation` |
| `fix/<description>` | Bug fixes | `fix/schema-loader-timeout` |
| `dev/<description>` | Infrastructure/tooling | `dev/ci-pipeline-update` |
| `docs/<description>` | Documentation only | `docs/add-runbook` |
| `refactor/<description>` | Code restructuring | `refactor/temporal-activities` |

### 7.3 Conventional Commits

Format: `<type>: <short description>`

| Type | When to Use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, whitespace (no code change) |
| `refactor` | Code restructuring (no behavior change) |
| `test` | Adding or updating tests |
| `chore` | Build, CI, tooling changes |
| `perf` | Performance improvement |

### 7.4 PR Process

1. Create branch from `main`
2. Commit with conventional commit messages
3. Push branch and open PR targeting `main`
4. Fill out PR template (Why, What Changed, How to Review, How to Test)
5. CI must pass (all required status checks)
6. Squash merge (keeps history clean)

---

## 8. GitHub Repository Setup

### 8.1 Branch Protection (Repository Rulesets)

**main branch:**
- Require pull request (no direct push)
- Required status checks: Code Quality, Secrets Detection, Unit Tests, uv Lock Check, PR Summary

### 8.2 CODEOWNERS

Single owner pattern with explicit paths for clarity:

```
* @<owner>
/backend/             @<owner>
/workers/             @<owner>
/development/         @<owner>
/.github/             @<owner>
/docs/                @<owner>
/dev/                 @<owner>
pyproject.toml        @<owner>
uv.lock               @<owner>
.pre-commit-config.yaml @<owner>
```

### 8.3 Dependabot

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    target-branch: "main"
    labels: ["dependencies", "ci"]
```

### 8.4 PR Auto-labeling

`labeler.yml` maps file path patterns to labels. PR labels are auto-applied via `actions/labeler`:

| Label | Triggered By |
|-------|-------------|
| `backend` | Changes in `backend/**` |
| `workers` | Changes in `workers/**` |
| `tests` | Changes in `tests/**` |
| `documentation` | Changes in `docs/**`, `dev/**`, `*.md` |
| `ci` | Changes in `.github/**` |
| `infrastructure` | Changes in `development/**`, `containerlab/**` |
| `schemas` | Changes in schema directories, `library/**` |
| `config` | Changes in `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.editorconfig` |

### 8.5 Issue Templates (YAML-based Forms)

Three templates in `.github/ISSUE_TEMPLATE/`:

**bug_report.yml:**
- Title prefix: `[Bug]:`
- Labels: `["bug"]`
- Fields: description, steps to reproduce, expected behavior, actual behavior, component dropdown, environment

**feature_request.yml:**
- Title prefix: `[Feature]:`
- Labels: `["enhancement"]`
- Fields: use case, proposed solution, alternatives considered, component dropdown

**task.yml:**
- Title prefix: `[Task]:`
- Labels: `["task"]`
- Fields: description, acceptance criteria (checklist), component dropdown

All templates share a component dropdown: Backend, Workers, CI/CD, Docker/Infrastructure, Documentation, Other.

### 8.6 PR Template

`.github/pull_request_template.md` sections:

1. **Why** -- Problem being solved, `Closes #<issue>`
2. **What Changed** -- Bullet list of behavior changes
3. **How to Review** -- Key files, risky areas, alternatives considered
4. **How to Test** -- Runnable commands with expected output
5. **Impact & Rollout** -- Checklist: backward compatible, no new deps, no config changes, no migrations
6. **Checklist** -- Tests added, linting passes, changelog fragment, documentation updated

---

## 9. GitHub Actions CI/CD

### 9.1 Workflow Architecture

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `quality.yml` | Called by other workflows | Reusable quality checks (lint, security, tests) |
| `pr-validation.yml` | PR to main | PR gates: calls quality + issue/changelog enforcement |
| `build-artifacts.yml` | Push tag `v*` | Docker build + package build |
| `release.yml` | Manual dispatch | Changelog build, tag, GitHub Release |
| `issue-automation.yml` | Issue opened or closed | Bug triage + issue close guard |

**Design principle:** Quality checks (linting, security scanning, testing) are defined once in `quality.yml` as a reusable `workflow_call` workflow. `pr-validation.yml` calls it, eliminating duplication.

Shared environment (defined in `quality.yml`):

```yaml
env:
  PYTHON_VERSION: "3.12"
  UV_VERSION: "latest"
```

### 9.2 Path-based Conditional Jobs

The `quality.yml` workflow uses `dorny/paths-filter@v3` with a centralized `.github/file-filters.yml` to skip unnecessary jobs when unrelated files change:

```yaml
# .github/file-filters.yml
python:
  - "**/*.py"
  - "pyproject.toml"
  - "uv.lock"
yaml:
  - "**/*.yml"
  - "**/*.yaml"
  - ".yamllint.yml"
documentation:
  - "docs/**"
  - "dev/**"
  - "*.md"
```

### 9.3 Reusable Quality Checks (`quality.yml`)

A `workflow_call` workflow invoked by `pr-validation.yml`. Accepts an `run-integration-hygiene` boolean input to optionally run offline integration tests.

Jobs:

1. **changes** -- Path detection using file-filters.yml (always runs)
2. **code-quality** -- `ruff check .` + `ruff format --check .` + `mypy` (if python changed; mypy with continue-on-error)
3. **yaml-lint** -- `yamllint .` (if yaml changed)
4. **security-scanning** -- Bandit security scan (hard gate) + SARIF upload (if python changed)
5. **secrets-detection** -- Gitleaks scan (always runs)
6. **uv-lock-check** -- `uv lock --check` (always runs)
7. **unit-tests** -- `pytest tests/unit/` with coverage + Codecov upload + JUnit XML (if python changed)
8. **integration-hygiene** -- `pytest tests/integration/ -k hygiene` (opt-in via input, depends on unit-tests)
9. **quality-gate** -- Aggregation gate: depends on all above, fails if any required job failed

**Aggregation gate pattern:**

```yaml
quality-gate:
  if: always()
  needs: [code-quality, security-scanning, secrets-detection, uv-lock-check, unit-tests, integration-hygiene]
  steps:
    - name: Check results
      run: |
        if [[ "${{ needs.code-quality.result }}" == "failure" ]] || ...; then
          exit 1
        fi
```

This ensures the quality-gate job runs even when upstream jobs are skipped (path filtering), and correctly aggregates pass/fail status. Callers depend on `quality` as a single pass/fail signal.

### 9.4 PR Validation Pipeline

Calls `quality.yml` for all code quality checks, plus PR-specific gates:

1. **quality** -- Reusable workflow call to `quality.yml` (runs all quality checks)
2. **issue-link-check** -- Enforces `Closes/Fixes/Resolves #N` in PR body (skips dependabot PRs)
3. **changelog-check** -- Enforces changelog fragment in PR (skips dependabot, `skip-changelog` label)
4. **labeler** -- Auto-label PRs based on file paths (always runs)
5. **wiki-reminder** -- Comment on PR if workflow files changed (reminder to update docs)
6. **pr-summary** -- Aggregation gate: checks results of quality, issue-link-check, changelog-check

### 9.5 Build Artifacts (Version Tags)

Triggered on tags matching `v*`:

- **build-docker** -- Uses `docker/setup-buildx-action`, builds from `development/Dockerfile`
- **build-package** -- `uv build --package <name>` for each workspace package, uploads `dist/` as artifact

### 9.6 Issue Automation (Issue Opened/Closed)

A single workflow (`issue-automation.yml`) handles two issue lifecycle events:

**Bug triage** (on issue opened): If the issue was created from the Bug Report template, adds the `triage` label and posts an automated welcome comment.

**Close guard** (on issue closed): Prevents premature manual closures by checking whether the issue still has open (unmerged) PRs linked via `Closes #N` / `Fixes #N` / `Resolves #N`. If an unmerged PR is found, **reopens the issue** and leaves a comment listing the linked PR(s) with a pointer to the issue management guidelines.

This enforces the policy documented in `dev/guidelines/issue-management.md`: issues must only be closed by merging their associated PR into `main`.

### 9.7 Pinned Action Versions

| Action | Version |
|--------|---------|
| actions/checkout | @v6 |
| actions/setup-python | @v6 |
| actions/upload-artifact | @v6 |
| actions/labeler | @v6 |
| actions/github-script | @v7 |
| astral-sh/setup-uv | @v7 |
| dorny/paths-filter | @v3 |
| codecov/codecov-action | @v5 |
| github/codeql-action | @v4 |
| gitleaks/gitleaks-action | @v2 |
| docker/setup-buildx-action | @v3 |
| marocchino/sticky-pull-request-comment | @v2 |

---

## 10. GitHub Projects Workflow

Uses **GitHub Projects V2** with a Board view.

**Status field columns:**

| Column | Meaning |
|--------|---------|
| **Backlog** | Triaged issues not yet started |
| **In Progress** | Actively being worked on |
| **In Review** | PR open, waiting for review/merge |
| **Done** | Merged and closed |

**Issue lifecycle:**
1. Create issue from template (bug, feature, or task)
2. Add to project board (lands in Backlog)
3. When starting work: move to In Progress, create feature branch
4. When PR opened: move to In Review
5. When PR merged: move to Done, close issue with comment referencing PR

**Closing issues:** Always reference the PR in the close comment: `Closed by #<PR number>` or use `Closes #<issue>` in the PR description for automatic closing.

---

## 11. Testing Strategy

### 11.1 Directory Structure

```
tests/
  __init__.py
  conftest.py               # Shared fixtures for all tests
  unit/
    __init__.py
    test_<module>.py         # One test file per source module
  integration/
    __init__.py
    test_<module>.py         # Tests requiring external services
```

### 11.2 Pytest Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers --tb=short"
asyncio_mode = "auto"
timeout = 300
markers = [
    "unit: Unit tests (no external dependencies)",
    "integration: Integration tests (require running services)",
    "slow: Slow tests (>30s)",
]
```

`--strict-markers` ensures all markers are registered in config, preventing typos.

### 11.3 Coverage

```toml
[tool.coverage.run]
source = ["backend/<import_name>", "workers/<import_name>"]
omit = ["*/tests/*", "*/__pycache__/*", "*/migrations/*"]

[tool.coverage.report]
show_missing = true
skip_empty = true
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.",
    "if TYPE_CHECKING:",
    "pass",
]
```

CI uploads XML coverage to **Codecov** via `codecov/codecov-action`.

### 11.4 Shared Fixtures Pattern

`tests/conftest.py` contains fixtures for:
- Sample data matching schemas (device configs, sessions, interfaces)
- Full topology fixtures (all devices with relationships)
- Mock API response fixtures matching the exact shape of external service responses
- Environment-based credentials with sensible defaults

Fixtures use realistic data that mirrors `seed_data.yml` so tests validate the same data shapes that production uses.

---

## 12. Documentation Strategy

### 12.1 Context Nuggets Pattern (ADR-0001)

**Problem:** Traditional monolithic documentation (long READMEs, wikis) doesn't work well for AI agents -- large docs exceed context windows and lack task-specific focus.

**Solution:** Organize developer documentation into small, focused files by purpose and audience, following the pattern established by opsmill/infrahub.

### 12.2 dev/ Directory Structure

| Directory | Content | Audience |
|-----------|---------|----------|
| `dev/adr/` | Architecture Decision Records | Human + AI |
| `dev/commands/` | AI agent command workflows | AI agents |
| `dev/guidelines/` | Coding standards and conventions (rules) | Human + AI |
| `dev/guides/` | Step-by-step procedures (how-to) | Human + AI |
| `dev/knowledge/` | Architecture explanations (reference) | Human + AI |
| `dev/prompts/` | Prompt templates for thinking tasks | Human |
| `dev/skills/` | Domain-specific AI agent skills | AI agents |

**Key distinction:**
- **Guidelines** = rules and standards (what you must do): python.md, git-workflow.md, changelog.md, repository-organization.md
- **Guides** = step-by-step procedures (how to do something): running-tests.md, adding-schemas.md
- **Knowledge** = architecture explanation (what things are and why): backend/architecture.md, workers/architecture.md

Guides and knowledge are organized by package subdirectory: `dev/guides/backend/`, `dev/knowledge/workers/`.

### 12.3 Root Documentation Files

| File | Purpose |
|------|---------|
| `README.md` | Project overview, quickstart, tech stack, architecture diagram |
| `CONTRIBUTING.md` | Setup instructions, development workflow, branch naming, key commands |
| `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 |
| `SECURITY.md` | Vulnerability reporting, security tools used, supported versions |
| `AGENTS.md` | Comprehensive AI agent knowledge map (entry point for all AI agents) |
| `CLAUDE.md` | Redirect to AGENTS.md (required by Claude Code) |
| `CHANGELOG.md` | Towncrier-managed changelog |
| `LICENSE` | Apache-2.0 |

### 12.4 AI Agent Integration

`.claude/commands` symlinks to `dev/commands/` and `.claude/skills` symlinks to `dev/skills/`. This lets Claude Code automatically discover command workflows and skills without duplicating content.

`CLAUDE.md` contains only a redirect to `AGENTS.md` -- this avoids duplication while satisfying Claude Code's convention of reading CLAUDE.md.

`AGENTS.md` is the comprehensive knowledge map containing: project description, repository structure tree, workspace architecture, key commands, coding standards summary, git workflow summary, changelog instructions, dev/ directory map, infrastructure table, and domain-specific context.

### 12.5 ADR Template

```markdown
# ADR-XXXX: Title

## Status
Proposed | Accepted | Deprecated | Superseded by ADR-XXXX

## Date
YYYY-MM-DD

## Context
What is the issue motivating this decision?

## Decision
What is the change we are making?

## Consequences
### Positive
- What becomes easier?
### Negative
- What becomes harder?
```

### 12.6 When to Update Documentation

| Change Type | Update Required |
|-------------|----------------|
| New feature | AGENTS.md (if it changes project structure), dev/knowledge/ (architecture), dev/guides/ (if new procedure) |
| New tool/dependency | AGENTS.md (key commands), dev/guidelines/ (if new standard) |
| Architecture decision | dev/adr/ (new ADR) |
| Workflow/CI change | PR triggers wiki-reminder comment automatically |
| API/schema change | docs/ (user-facing), dev/knowledge/ (architecture) |

---

## 13. Changelog Management

### 13.1 Towncrier Configuration

```toml
[tool.towncrier]
package = "<package_name>"
directory = "changelog"
filename = "CHANGELOG.md"
title_format = "## [{version}] - {project_date}"
issue_format = "[#{issue}](https://github.com/<org>/<repo>/issues/{issue})"
```

Fragment types: `added`, `changed`, `deprecated`, `removed`, `fixed`, `security`.

### 13.2 Fragment Naming

```bash
# With issue number
echo "Added BGP session validation" > changelog/42.added.md

# Without issue number
echo "Fixed schema loader timeout" > changelog/+fix-timeout.fixed.md
```

### 13.3 When to Add vs Skip

**Add a fragment for:** User-facing changes, breaking changes, security fixes.

**Skip for:** Internal refactoring, CI/CD updates, documentation-only changes, test-only changes. Add the `skip-changelog` label to the PR to bypass the CI check.

### 13.4 PR Enforcement

CI blocks PRs that don't include a changelog fragment (`changelog-check` job in `pr-validation.yml`). The check is skipped for dependabot PRs and PRs with the `skip-changelog` label.

### 13.5 Building the Changelog

Changelog building is automated by the release workflow (`release.yml`). Manual building is still available:

```bash
# Preview
uv run towncrier build --draft

# Build (consumes fragments, updates CHANGELOG.md)
uv run towncrier build --version X.Y.Z
```

---

## 14. Release Process

Releases are automated via the `Release` workflow (`.github/workflows/release.yml`), triggered manually via `workflow_dispatch`.

### 14.1 Release Flow

1. All feature work merges to `main` via PRs (each PR must include a changelog fragment)
2. CI runs on PR (unit + integration tests)
3. When ready for release: Go to **Actions → Release → Run workflow**, enter version (e.g., `0.2.0`)
4. The workflow automatically:
   - Validates all closed issues since last tag have changelog fragments (completeness guard)
   - Compiles fragments into `CHANGELOG.md` via Towncrier
   - Commits the updated changelog to `main`
   - Creates and pushes an annotated git tag (`v0.2.0`)
   - Creates a GitHub Release with the generated notes
   - Tag push triggers `build-artifacts.yml` (Docker + Python packages)

### 14.2 Completeness Validation

Before publishing, the release workflow checks that every issue closed since the last `v*` tag has a corresponding `changelog/<issue>.*.md` fragment. Issues labeled `duplicate`, `wontfix`, `question`, `invalid`, or `skip-changelog` are excluded. Orphan fragments (no matching closed issue) produce warnings but don't block the release.

### 14.3 Emergency Releases

Use the `skip-validation` checkbox when triggering the workflow to bypass the completeness check.

### 14.4 Prerequisites

The release workflow pushes directly to `main`. Requires:
- "Repository admin" role in the "Protect main" ruleset bypass list (set to "Always")
- A Fine-grained PAT (`RELEASE_PAT` secret) with Contents: Read/Write, scoped to this repo

---

## 15. .gitignore Conventions

Organize `.gitignore` with section headers for clarity:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/

# Testing & Coverage
htmlcov/
.coverage
*.xml
.pytest_cache/

# IDE & Editors
.vscode/
.idea/
*.swp
*~

# Project-specific
*.log
.env
generated-configs/

# Lab artifacts
clab-*/

# OS files
.DS_Store
Thumbs.db

# Temporary
PLAN.md
```

---

## Quick Reference: New Project Setup Checklist

1. Create repository with `main` branch (default)
2. Initialize uv workspace: `uv init --no-package && uv init backend && uv init workers`
3. Configure pyproject.toml (workspace, ruff, mypy, pytest, coverage, towncrier)
4. Add root config files (.editorconfig, .yamllint.yml, .markdownlint-cli2.yaml, .python-version)
5. Create `.github/` structure (workflows, issue templates, PR template, CODEOWNERS, labeler, dependabot, file-filters)
6. Create `dev/` structure (adr, commands, guidelines, guides, knowledge, prompts, skills)
7. Create root docs (README, CONTRIBUTING, AGENTS, CLAUDE, CODE_OF_CONDUCT, SECURITY, LICENSE)
8. Set up pre-commit: `.pre-commit-config.yaml` + `uv run pre-commit install`
9. Create invoke tasks: `tasks/` directory with namespace organization
10. Enable GitHub Advanced Security (CodeQL, secret scanning, Dependabot alerts)
11. Create branch protection ruleset for main
12. Create GitHub Projects V2 board with Status field
13. Create initial ADR: `dev/adr/0001-context-nuggets-pattern.md`
14. Commit, push, verify CI passes
