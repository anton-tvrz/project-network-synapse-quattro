"""Invoke task runner — unified CLI for development commands.

Usage:
    uv run invoke --list          # Show all available tasks
    uv run invoke format          # Format all code
    uv run invoke lint            # Lint all code
    uv run invoke backend.test-unit  # Run backend unit tests
"""

from invoke import Collection

from . import backend, dev, docs, main, workers

ns = Collection()

# Root-level tasks (format, lint, scan, check-all)
ns.add_task(main.format_code, name="format")
ns.add_task(main.lint, name="lint")
ns.add_task(main.scan, name="scan")
ns.add_task(main.check_all, name="check-all")

# Sub-collections
ns.add_collection(Collection.from_module(backend), name="backend")
ns.add_collection(Collection.from_module(workers), name="workers")
ns.add_collection(Collection.from_module(dev), name="dev")
ns.add_collection(Collection.from_module(docs), name="docs")
