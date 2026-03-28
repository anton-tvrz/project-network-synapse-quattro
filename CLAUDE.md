# Claude Code Configuration

See [AGENTS.md](AGENTS.md) for full project context.

## Quick Reference
- Lint: `uv run invoke lint`
- Format: `uv run invoke format`
- Test: `uv run invoke backend.test-unit`
- Start infra: `uv run invoke dev.deps`
- Start worker: `uv run invoke workers.start`
- Branch from `main`, PR to `main`
- Conventional commits (feat:, fix:, docs:, etc.)

## Test-Driven Development

This project follows strict TDD. When generating code:
1. **Always produce the test file first.** If asked for a new workflow, generate `test_<workflow>.py` before `<workflow>.py`. If asked for a new schema, generate `test_<schema>.py` before `<schema>.yml`.
2. Follow Red-Green-Refactor: failing test → minimum implementation → refactor.
3. Never create a source file without its corresponding test file.
4. Use pytest fixtures from `tests/conftest.py` for shared test data.
5. Coverage target: ≥80% on new code.

This is a hard rule, not a suggestion.
