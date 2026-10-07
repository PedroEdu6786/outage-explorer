# Facility-filter backend verification

Date: **2026-10-07**. Scope: portable backend acceptance of this feature, not live
runtime, web-project, deployment or production acceptance. Phase 3 shipped source
in `6142ec5`; this phase completes integration regressions, current documentation
and the evidence record. Existing dated checkpoints remain historical.

## Acceptance evidence

| Criterion | Evidence and limits |
| --- | --- |
| AC1 | `tests/integration/test_query_worker_transport.py::test_filtered_preview_real_parquet_subprocess_pages` uses real multi-facility, three-day unified Parquet and paired JSON worker transport for both grains: facility-only, inclusive intersection, leading-zero distinction, quoted IDs, unmatched IDs, unchanged unfiltered/date-only and ordered pages. `test_filtered_http_real_worker_snapshot_pages` in `test_data_api_http.py` adds actual HTTP + AccessService + verified resource cache + protocol-v2 subprocess for Analyst/Admin × both grains. |
| AC2 | Domain tests cover exact byte bounds, multibyte identities, invalid types, controls, whitespace and surrogates. HTTP rejects duplicates, malformed raw UTF-8 and national filtering before resources; escaped literal-percent IDs stay valid. Worker independently rejects malformed/unsupported selection. `infrastructure/duckdb/previews.py` binds the equality value as a parameter; real quoted-ID cases confirm literal matching. Contract/fixture/catalog tests validate per-grain capabilities and paired OpenAPI. |
| AC3 | Real HTTP pages concatenate to explicit binary-ordered expected identities without skips/duplicates; every page revisits identically. Fake publication points to a second real candidate with changed capacity/descriptors: old sequences retain their original generation/pinned data with identical page revisits, while a new initial browse observes new values. Cursor/filter mixtures fail before execution. Portable store tests retain fixed 60-second expiry, store loss, active-reader pin accounting, UTF-8 metadata capacity rollback and failed-reaping retention/reconciliation. |
| AC4 | Real application AccessService and portable HTTP denial matrices cover both detail grains: Viewer, absent/expired/revoked session, foreign owner cursor and changed role; spies prove no preparation/execution (and direct-use-case tests no publication lookup). Operational session repositories are controlled ports; these tests do not prove live Cognito/PostgreSQL/session mapping. |
| AC5 | Unfiltered/date-only real HTTP and worker results remain unchanged; catalog/OpenAPI/fixtures agree by grain. HTTP contract, UI API handoff, preview-flow and living backend requirements describe exact filtering and strict-decoder compatibility. Runtime profile tests and worker protocol/response tests reject version 1/mismatches without fallback. |
| AC6 | Backend checks and exact portable results are recorded below; unavailable disposable PostgreSQL and actual-host checks remain explicit. Architecture negative fixtures are retained. No web work or UI acceptance is claimed. |

AC1–AC6 are satisfied for the approved portable backend scope; TR2 runtime controls
are preserved in source and covered by controlled regressions, not certified by
these tests. Broader isolation, capacity and deployment evidence remains open.

## Reproducible checks

Commands run from the repository root using existing `.venv` dependencies:

```sh
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
```

Ruff lint and format passed (**454 files**); strict mypy passed (**148 source
files**). Parent also ran `.venv/bin/python -m pip check`: no broken requirements.

No `OUTAGE_TEST_POSTGRES_DSN` was supplied. Tests requiring the explicit disposable
`database` fixture were deselected using this temporary collection plugin, saved
as `/private/tmp/outage_preview_nodb.py`:

```python
def pytest_collection_modifyitems(config, items):
    excluded = [
        item for item in items if "database" in getattr(item, "fixturenames", ())
    ]
    if excluded:
        print(f"Disposable PostgreSQL fixture cases excluded: {len(excluded)}")
        config.hook.pytest_deselected(items=excluded)
        items[:] = [item for item in items if item not in excluded]
```

The plugin changes collection only; it neither substitutes fake databases nor
claims the deselected tests passed. Normal fixtures still enforce an explicit
DSN if run without this exclusion. Do not use configured application RDS as a test
fallback or start a database implicitly.

Targeted command:

```sh
PYTHONPATH=/private/tmp:src .venv/bin/python -m pytest -q -rs -p outage_preview_nodb \
  tests/integration/test_catalog_preview.py tests/integration/test_data_api_http.py \
  tests/integration/test_query_worker_transport.py tests/unit/test_preview_filters.py \
  tests/unit/test_worker_protocol.py tests/unit/test_worker_response_decoding.py \
  tests/unit/test_data_api_contract.py tests/integration/test_api_documentation.py \
  tests/architecture/ tests/test_local_analytical.py
```

Targeted result: **521 passed, 24 deselected** (explicit disposable PostgreSQL
fixture cases), in 126.25 seconds. The four added real HTTP/worker cases pass for
Analyst/Admin and both detail grains.

Full portable command (default runtime/Docker checks stay opt-in and skip):

```sh
PYTHONPATH=/private/tmp:src .venv/bin/python -m pytest -q -rs \
  -p outage_preview_nodb -m 'not live_provider'
```

Full portable result: **2,309 passed, 41 skipped, 195 deselected, 17 subtests
passed**, in 198.38 seconds. All 195 deselections require the disposable
PostgreSQL fixture. The 41 skips comprise 20 explicitly opt-in runtime/Docker
acceptance cases, 18 native Linux `prlimit` cases, one Linux path-descriptor case
and two additional explicit-disposable-PostgreSQL cases. Architecture is included
in both commands. No live-provider selection or actual-host runtime invocation ran.

A local check of relative file links in all touched Markdown files plus this
record resolved **133 links** (file existence, not remote URLs/anchor rendering).
The shared data operations' request/response/security definitions and shared schema
components match across both OpenAPI documents; complete documents intentionally
have different titles, descriptions/tags and additional served auth/health paths.
Both JSON documents and fixtures parse, and targeted/full contract tests validate
fixtures and served contract parity. `git diff --check` passed.

## Runtime and remaining evidence

- Query and preview request/success/error transport requires **protocol 2**.
  Tabular encoding and SQL-inspection protocol remain **1**. Existing pinned images
  must be rebuilt from matching source and reviewed, with a fresh matching profile
  and reviewed evidence identity before use. The profile generator explicitly
  selects the current paired version; old profiles are rejected, never upgraded.
- No image was built, pulled or activated. No service was started/restarted,
  source/cloud/browser resources accessed, publication/reset performed or historical
  evidence rewritten in this phase. A manual API restart or data refresh does not
  rebuild the matching worker image. Running-service activation is separate work.
- PostgreSQL-backed session/publication/HTTP integration remains unrun without a
  disposable DSN. Native Linux `prlimit`, descriptor/path, Docker denial/termination,
  quota/spill and current-image actual-host acceptance remain unverified here.
  Portable subprocess tests prove real DuckDB behavior, not an OS sandbox.
- Existing open high-water/spill, S3 performance, API/refresh overlap, measured
  budget, session mapping and EC2 topology/storage acceptance stays open. See
  [runtime evidence](../data-api/runtime-evidence.md) and the
  [worker runbook](../../../infrastructure/analytical-worker/README.md).
- Web UI implementation, consumer rollout and live Analyst/Admin browsing are
  outside this repository and this acceptance scope. API handoff does not prove
  those consumers accepted the expanded catalog metadata.

Subsequent local runtime upgrade preparation is recorded separately in
[runtime-upgrade.md](runtime-upgrade.md), including actual native protocol-v2
checks, the corrected synthetic fixture and pending review/activation status.
It does not retroactively change this phase's portable verification results.
