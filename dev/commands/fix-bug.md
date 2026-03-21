# Fix Bug Workflow

Follow these steps to diagnose and fix a bug:

## 1. Understand the Bug
- Read the bug report or issue description
- Identify the expected vs. actual behavior
- Determine which package is affected (`network_synapse` or `synapse_workers`)

## 2. Reproduce
- Write a failing test in `tests/unit/` that demonstrates the bug
- Run: `uv run invoke backend.test-unit` to confirm it fails

## 3. Investigate
- Read the relevant source code in `backend/network_synapse/` or `workers/synapse_workers/`
- Check `dev/knowledge/` for architecture context
- Use `ruff check` to catch any obvious issues

## 4. Fix
- Make the minimal change to fix the bug
- Follow coding standards in `dev/guidelines/python.md`
- Ensure the failing test now passes

## 5. Verify
- Run full test suite: `uv run invoke backend.test-all`
- Run linter: `uv run invoke lint`
- Add changelog fragment: `echo "Fixed <description>" > changelog/<issue>.fixed.md`

## 6. Commit
- Branch: `fix/<short-description>`
- Commit message: `fix: <description> (#<issue>)`
