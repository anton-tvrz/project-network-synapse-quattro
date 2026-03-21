"""Documentation tasks — linting, validation."""

from __future__ import annotations

from invoke import task

from .shared import execute_command


@task
def lint_yaml(ctx):
    """Lint all YAML files."""
    execute_command(ctx, "yamllint .")


@task
def lint_markdown(ctx):
    """Lint all Markdown files."""
    execute_command(ctx, "npx markdownlint-cli2 '**/*.md' '#node_modules' '#library' '#.venv'", warn=True)


@task(pre=[lint_yaml])
def lint_all(ctx):
    """Run all documentation linters."""
    print("All documentation lints complete.")
