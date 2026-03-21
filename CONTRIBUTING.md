# Contributing to Network Synapse Quattro

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/anton-tvrz/project-network-synapse-quattro.git
cd project-network-synapse-quattro

# Initialize submodules
git submodule update --init --recursive

# Install dependencies (requires uv: https://docs.astral.sh/uv/)
uv sync --all-groups

# Install pre-commit hooks
uv run pre-commit install

# Install pre-push hook (blocks direct pushes to main)
ln -sf ../../.githooks/pre-push .git/hooks/pre-push

# Verify setup
uv run invoke backend.test-unit
```

## Local Environment

This project runs entirely on macOS. Requirements:

- **macOS** with Apple Silicon (M-series)
- **OrbStack** for Docker (recommended over Docker Desktop)
- **Python 3.12** via uv
- **Containerlab** for the Nokia SR Linux lab

## Development Workflow

1. **Create a branch** from `main` (never commit directly to `main`)
2. **Make changes** following our [coding standards](dev/guidelines/python.md)
3. **Run quality checks**: `uv run invoke lint`
4. **Run tests**: `uv run invoke backend.test-unit`
5. **Add a changelog fragment** if the change is user-facing (see [changelog guide](dev/guidelines/changelog.md))
6. **Open a PR** targeting `main` (see [PR best practices](dev/guides/pull-request-best-practices.md))
7. **CodeRabbit** will automatically post an AI review -- address any flagged issues before requesting human review

## Branch Naming

- `feature/<description>` -- New features
- `fix/<description>` -- Bug fixes
- `dev/<description>` -- Infrastructure / tooling
- `docs/<description>` -- Documentation only

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add BGP session validation
fix: handle schema loader timeout (#42)
docs: update infrastructure guide
```

## Key Commands

| Command                           | Description     |
| --------------------------------- | --------------- |
| `uv run invoke format`            | Format all code |
| `uv run invoke lint`              | Lint all code   |
| `uv run invoke backend.test-unit` | Run unit tests  |
| `uv run invoke backend.test-all`  | Run all tests   |
| `uv run invoke scan`              | Security scan   |

## Project Documentation

- **[AGENTS.md](AGENTS.md)** -- Full project context and architecture
- **[dev/guidelines/](dev/guidelines/)** -- Coding standards
- **[dev/knowledge/](dev/knowledge/)** -- Architecture docs
- **[dev/guides/](dev/guides/)** -- How-to guides (including [PR best practices](dev/guides/pull-request-best-practices.md))
- **[.coderabbit.yaml](.coderabbit.yaml)** -- AI code review configuration (CodeRabbit)

## Reporting Bugs

If you encounter an issue or a bug:

1. Check the existing issues to see if it has already been reported.
2. If not, open a new issue using the **Bug Report** template. Please fill out the required steps to reproduce and environment details so we can investigate quickly.

## Questions?

Open an issue or check the existing documentation in the `dev/` directory.
