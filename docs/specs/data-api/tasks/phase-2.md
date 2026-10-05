# Tasks: Durable generation and refresh coordination
> Status: complete · Slug: data-api · Plan: ../plan.md · Spec: ../spec.md

## Phase 2 (plan phase 2)

- [x] **T2.1** Create publication/run state types and transaction ports — `src/outage_explorer/domain/publication.py`, `src/outage_explorer/application/ports/publication.py`, `src/outage_explorer/application/ports/refresh.py`; represent immutable admission snapshots, historical publication, lease epochs and pending/unknown outcomes without query metadata. (FR13–FR19, FR23, FR26–FR30, TR8)
- [x] **T2.2** Create additive operational migration — `src/outage_explorer/infrastructure/postgresql/migrations/versions/0002_data_api.py`; constrain idempotency/run identity, coordination singleton and historical publication, preserving existing access schema. Check migration numbering before creation. Depends on T2.1. (FR13–FR19, FR26–FR30, TR8)
- [x] **T2.3** Create parameterized short-transaction coordination/publication adapter — `src/outage_explorer/infrastructure/postgresql/publication.py`; implement atomic admission/claim/lease/epoch checks and generation/run publication with fresh-connection reconciliation after ambiguous commits. Depends on T2.2. (FR18–FR19, FR26–FR30, TR8)
- [x] **T2.4** Create Admin admission/status/latest services and configured interval validation — `src/outage_explorer/application/services/refresh.py`, `src/outage_explorer/settings.py`; authorize before lookup, freeze settings, replay scoped keys before changed configuration, reject overrides/conflicts and enforce initial interval/all-grain scope. Depends on T2.3. (FR1, FR13–FR17, FR23, FR29, TR1, TR8)
- [x] **T2.5** Create disposable PostgreSQL transaction/fault tests — `tests/integration/test_data_api_postgresql.py`; verify idempotency races, denied reads, no-run versus unavailable, history-based recovery, compare-and-swap publication, stale owners and commit ambiguity. Depends on T2.4. (FR13–FR19, FR26–FR30, TR8)
- [x] **T2.C** Checkpoint: verify coordination and service acceptance with real local PostgreSQL, Ruff/mypy and architecture checks — `tests/integration/test_data_api_postgresql.py`, `tests/architecture/test_import_boundaries.py`, `docs/specs/data-api/tasks/phase-2.md`; no migration on RDS is implied. Depends on T2.5. (AC1, AC14–AC15, AC17–AC20, AC24, AC27–AC31)

Phase 2 evidence (2026-10-05): disposable PostgreSQL 18.6 on loopback port
5432; 104 phase/architecture checks passed, including scoped concurrent admission,
atomic publication/CAS, immutable history, frozen replay before changed settings,
healthy/expired leases, stale-owner rejection, historical recovery after a later
publication, and committed/rolled-back/unavailable commit-response fault injection.
Ruff lint/format and strict mypy pass. Unit/architecture regression: 751 passed.
AC1 is verified for fresh Admin refresh authorization, including role revocation;
AC14–15, AC18–20 and AC24 are verified at admission/storage boundaries; AC27–31
are verified for durable coordination/reconciliation. AC17 verifies bounded report
preservation and null unknown counts here; connector quality mapping and complete
artifact verification remain phase 3, as do supervised worker runtime and HTTP
transport. No RDS migration, live source retrieval or publication was performed.

Full regression run: 1,374 passed, 17 subtests passed, one setup error in the
concurrently added user-access browser acceptance fixture:
`ThreadedWSGIServer` has no `set_app` (`tests/acceptance/test_user_access_browser.py:23`).
The focused phase checkpoint passed; full-suite success is not claimed.
Package sdist/wheel build passed.
