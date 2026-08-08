"""Invoke task runner — unified CLI for development commands.

Usage:
    uv run invoke --list          # Show all available tasks
    uv run invoke format          # Format all code
    uv run invoke lint            # Lint all code
    uv run invoke backend.test-unit  # Run backend unit tests
"""

from invoke import Collection

from . import backend, collector, demo, dev, docs, main, presentation, workers
from .shared import load_env_file

# Load .env before any task runs, so tasks see the repo's configured values
# rather than whatever happens to be exported in the caller's shell (#189).
load_env_file()

ns = Collection()

# Root-level tasks (format, lint, scan, check-all)
ns.add_task(main.format_code, name="format")
ns.add_task(main.lint, name="lint")
ns.add_task(main.scan, name="scan")
ns.add_task(main.check_all, name="check-all")

# Sub-collections
ns.add_collection(Collection.from_module(backend), name="backend")
ns.add_collection(Collection.from_module(collector), name="collector")
ns.add_collection(Collection.from_module(workers), name="workers")
ns.add_collection(Collection.from_module(presentation), name="presentation")
ns.add_collection(Collection.from_module(dev), name="dev")
ns.add_collection(Collection.from_module(demo), name="demo")
ns.add_collection(Collection.from_module(docs), name="docs")
