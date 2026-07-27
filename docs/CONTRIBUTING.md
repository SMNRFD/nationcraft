# Contributing Guide

Thanks for your interest in improving NationCraft! This guide covers the
workflow, conventions, and review criteria.

## 1. Code of conduct

Be respectful. Be constructive. Personal attacks, harassment, or
discrimination will not be tolerated.

## 2. Workflow

1. **Open an issue** describing what you want to change and why.
2. **Fork & branch**: `git checkout -b feat/my-feature`.
3. **Write code + tests**: see sections below.
4. **Run all checks locally**:
   ```bash
   make format lint typecheck test
   ```
5. **Open a pull request** with a clear description and link to the issue.
6. **Address review feedback**; push follow-up commits (don't squash
   until merge).

## 3. Code style

- **Python 3.13+** with full type hints (`mypy --strict`).
- **Ruff** for lint and format (`line-length = 100`).
- **Pydantic v2** for all DTOs and config models.
- **Async everywhere** — no blocking I/O in service methods.
- **Docstrings** on every public class and function (triple-quoted,
  imperative mood).
- **No magic numbers** — push values into `Settings` or YAML.

## 4. Architecture rules

- Domain layer imports nothing from infrastructure.
- Application services depend on repository `Protocol`s, not concrete
  classes.
- Presentation (API + bot) depends on application services only.
- The bot talks to the backend *only* via the REST API client.
- New game content goes in YAML, not Python.
- New formulas should be exposed as hooks so extensions can override.

## 5. Tests

- Unit tests for domain & core logic (`tests/unit/`).
- Integration tests for services against in-memory SQLite
  (`tests/integration/`).
- API tests via `httpx` + ASGI transport (`tests/api/`).
- Plugin tests under `tests/plugin/`.
- Simulation tests under `tests/simulation/`.

Coverage target: **≥ 90%** on `src/nationcraft/`.

Run a single test file:

```bash
pytest tests/unit/test_event_bus.py -v
```

## 6. Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(market): add order expiry
fix(auth): refresh token rotation race
docs(plugin): clarify config schema
refactor(tick): extract phase loop
test(market): add cancel-refund test
chore(deps): bump aiogram to 3.13
```

## 7. Pull request template

```markdown
## Summary
What does this PR change?

## Why
What problem does it solve? Link issue.

## How
Brief description of approach.

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] `make lint typecheck test` passes
- [ ] Coverage not decreased

## Breaking changes
List any, or "None".

## Checklist
- [ ] No hardcoded secrets
- [ ] No TODOs left in code
- [ ] Docs updated (if user-facing)
```

## 8. Review criteria

Reviewers will check:

- **Correctness** — does it do what the issue asked?
- **Tests** — are there meaningful tests?
- **Architecture** — does it respect layer boundaries?
- **Performance** — no N+1 queries, no sync I/O in async paths.
- **Security** — auth checks present, inputs validated, no SQL injection.
- **Docs** — public APIs documented; user-facing changes documented.
- **Backwards compatibility** — or explicit breaking-change note.

## 9. Adding new game content

Prefer YAML edits over Python changes. Example workflow for a new
building:

1. Add the building to `game/data/buildings.yaml`.
2. If it requires a new tech, add it to `game/data/techs.yaml`.
3. Add a test verifying the YAML parses (`tests/unit/test_game_data.py`).
4. Open a PR.

## 10. Adding a new hook

1. Pick a name (`<system>.<action>`).
2. Invoke it in the service: `await HookRegistry.instance().invoke(name, default, **args)`.
3. Document it in `docs/EXTENSIONS.md`.
4. Add a unit test demonstrating an override.

## 11. Release process

1. Bump version in `pyproject.toml` and `nationcraft/__init__.py`.
2. Update `CHANGELOG.md` (Keep-a-Changelog format).
3. Tag: `git tag v1.x.y && git push --tags`.
4. CI builds the Docker image and pushes to the registry.

## 12. Getting help

- Open a discussion on GitHub.
- Join our Telegram dev chat: @nationcraft_devs.

Happy hacking!
