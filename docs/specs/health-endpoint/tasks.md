# Tasks: Project scaffold and health endpoint

- [x] Add `pyproject.toml`, `requirements-dev.txt`, and Python ignore rules.
- [x] Add application DTO/clock port/health service under `src/outage_explorer/application/`.
- [x] Add `src/outage_explorer/infrastructure/clock.py` and `bootstrap.py`.
- [x] Add HTTP factory, startup factory, and health route in `entrypoints/http/`.
- [x] Add unit and HTTP integration tests under `tests/unit/` and `tests/integration/`.
- [x] Add AST boundary checks and negative fixtures under `tests/architecture/`.
- [x] Add `.github/workflows/ci.yml` and run its available checks locally.
- [x] Update README, living context, agent enforcement status, and append devlog evidence.

Verification: 50 tests passed locally on Python 3.14.6; Ruff lint/format,
strict mypy, dependency consistency, sdist/wheel build, wheel-import smoke test,
and a live localhost HTTP probe passed. Python 3.12 is configured in CI but was
not available locally. No remote CI run, database readiness, or deployment is
claimed. The temporary local server was stopped after the smoke test.
