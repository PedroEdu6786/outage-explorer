# Plan: Project scaffold and health endpoint

1. Package `src/outage_explorer` using Python >=3.12, Flask 3.1, and Hatchling.
   Use a local venv and a resolved development requirements file. Use pytest,
   Ruff, and mypy for tests, formatting/linting, and strict application typing.
2. Put `HealthStatus` in application DTOs, `Clock` in application ports, and
   `HealthService` in application services. Infrastructure supplies `SystemClock`.
   This probe has no domain policy; do not invent domain entities or repositories.
3. Register an injected health Blueprint in the HTTP factory. `bootstrap` owns
   concrete construction. A dedicated HTTP startup factory delegates only to
   bootstrap so Flask CLI can load it without import-time application creation.
4. Check imports with Python AST analysis under `tests/architecture`. Resolve
   relative imports, inspect every module including package initializers, reject
   unknown root helpers and wildcard/dynamic imports, and constrain the startup
   exception to the dedicated forwarding factory. Inner-layer external imports
   use a reviewed pure-standard-library allowlist. Add negative fixtures and a
   dependency-cycle check. Static checks complement rather than prove purity.
5. Add behavior tests, local commands, and GitHub Actions on Python 3.12 and 3.14.
   Existing devlog scripts retain their separate standard-library workflow.
6. Synchronize living context and append verification evidence to the devlog.

No persistence is needed for liveness. PostgreSQL remains the selected database
for future operational adapters and integration tests, without a SQLite fallback.
