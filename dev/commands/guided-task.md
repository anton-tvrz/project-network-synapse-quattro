# Guided Task Workflow

A general-purpose workflow for implementing any task.

## 1. Understand the Task
- Read the task description carefully
- Identify which packages and files will be affected
- Check `dev/knowledge/` for relevant architecture docs

## 2. Plan
- Break the task into small, testable steps
- Identify dependencies between steps
- Consider edge cases and error handling

## 3. Implement
- Work through steps one at a time
- Follow `dev/guidelines/python.md` coding standards
- Write tests alongside implementation (TDD when possible)
- Keep commits small and focused

## 4. Quality Checks
- `uv run invoke format` — Format code
- `uv run invoke lint` — Lint code
- `uv run invoke backend.test-unit` — Run tests
- `uv run invoke backend.typecheck` — Type check (if applicable)

## 5. Document
- Update docstrings for new/modified functions
- Add changelog fragment if user-facing
- Update `dev/knowledge/` docs if architecture changed

## 6. Commit
- Use conventional commit messages
- Reference issue numbers where applicable
