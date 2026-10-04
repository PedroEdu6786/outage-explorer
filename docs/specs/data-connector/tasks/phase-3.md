# Phase 3: Bounded source adapter
> Status: complete (fixture source checkpoint) · Plan phase: 2 · Depends on: phase 2 evidence contracts

- [x] **T3.1** Add source page/request/bounds DTOs and protocol in `src/outage_explorer/application/ports/source.py`; pin the chosen HTTP dependency in `pyproject.toml` and `requirements-dev.txt` after resolving the adapter choice. Keep route allowlists, explicit inclusive dates, daily frequency and ordering identity in the contract. (FR4–FR6; TR1, TR5–TR8)
- [x] **T3.2** Add bounded recursive secret sanitization in `src/outage_explorer/infrastructure/eia/sanitization.py`; redact credential keys and actual configured values in echoed metadata/observations, record affected paths, sanitize failure messages, and prevent redacted observations silently changing modeled meaning. (FR6; TR4, TR5)
- [x] **T3.3** Add bounded sequential metadata/page retrieval in `src/outage_explorer/infrastructure/eia/source.py`: validate envelopes and totals, preserve accepted-page/global-row order across retries, continue short pages through the proposed empty terminator, detect stalled/repeated payloads and fail on empty routes or out-of-window dates. Bound requests/bytes/rows/pages/attempts/deadlines; retry only permitted failures with bounded Retry-After/backoff; constrain redirects. Keep live validation gated. (FR4–FR8; TR5–TR8)
- [x] **T3.4** Add source-quality reconciliation in `src/outage_explorer/infrastructure/eia/quality.py`: distinguish received counts, changing advertised totals and observed coverage; preserve the facility mismatch as a visible diagnostic independent of its literal numeric values. National/generator inconsistencies and failed/missing pages fail retrieval. (FR14–FR16; TR7)
- [x] **T3.5** Add transport-controlled fixtures in `tests/integration/test_eia_source.py` covering each route's full/short/empty pages, cross-page winners, retries, totals, progress failures, redirect restrictions and every configured cap; include nested/echoed secrets and exact artifact replay, plus recorded and differently sized facility mismatches paired with failed pages. (FR4–FR8, FR14–FR16; TR4–TR8)
- [x] **T3.C** Checkpoint: run `tests/integration/test_eia_source.py`, Parquet replay regressions and documented static/architecture checks; record results in `docs/specs/data-connector/tasks/phase-3.md`. Verify fixture portions of AC3–AC7 and AC13–AC15; AC3 live paging, Q3/Q4 ordering applicability and actual production bounds remain phase 6 gates. (AC3–AC7, AC13–AC15)


## Checkpoint evidence — 2026-10-03

`make check` passed on Python 3.14.6: dependency consistency, Ruff lint and
format (139 files), strict mypy (45 source files), **584 tests**, and sdist/wheel
builds. Pytest took 36.45 seconds; this is test duration, not a production resource
measurement. The source suite contains **143 tests** in
`tests/integration/test_eia_source.py`; another **4 tests** in
`tests/integration/test_eia_transport.py` exercise real HTTPX/httpcore behavior
against a controlled in-memory backend. The checkpoint also ran all 64 Parquet
candidate/evidence regressions, all 58 architecture cases, and the existing
national/detail, domain, health, startup and devlog suites. No live EIA/AWS/RDS
retrieval or publication was performed.

| Acceptance portion | Verified local evidence |
| --- | --- |
| AC3 fixture pagination | All three allowlisted daily routes retain full, short and successful empty-terminal pages. Offsets advance by actual received rows; ascending period/facility/generator request identity and accepted page/global-row order survive retries. Recorded observations also replay through the adapter, reordered explicitly into the proposed fixture sort without claiming observed live ordering. |
| AC4 retrieval failure | Empty routes, malformed metadata/envelopes/JSON/totals, conflicting request echoes, out-of-window dates, regressing/repeated pages, nonsequential requests and failed pages fail retrieval. Each configurable cap is exercised, including request/response/cumulative/output bytes, rows, pages, interval, attempts, timeout/deadline/backoff and JSON depth/nodes/fields. Failure poisons that retrieval and no successful summary is available. Active-generation preservation belongs to later application/publication integration. |
| AC5–AC7 sanitized replay and selection | Real Parquet preserves exact source numeric strings, request/retrieval identities, page/row/source positions, empty pages and metadata. Cross-page A/B/A plus a later invalid record produces the expected last-valid winner, identical duplicate, superseded and excluded dispositions; valid zero remains usable. Recursive key/value and URL-encoded secret sanitization records safe positional paths. Altered observations carry an unexpected-attribute marker and are excluded, and cannot fabricate source coverage or order. |
| AC13 observed coverage | Requested dates, received rows, original advertised-total strings and observed identifiers/dates remain distinct. Usable coverage remains a modeling result. Invalid-date rows retain interpretable identifiers; redacted rows are conservatively omitted from derived coverage/order. No roster completeness or missing-value zero filling is asserted. |
| AC14 facility diagnostic | Both the recorded 2,850/1,650 discrepancy and a differently sized 9/3 discrepancy remain visible and nonblocking. Failed-page versions fail. Changed facility totals are preserved individually; national/generator numeric inconsistencies fail. Leading-zero strings compare numerically without losing the source notation. |
| AC15 accounting | Source received counts match actual rows; replayed modeling reconciles selected/excluded/duplicate/superseded counts. Existing Parquet regressions verify distinct retained-invalid/absent/outside-interval accounting. |

HTTPX **0.28.1** is pinned in runtime and resolved development dependencies.
The adapter uses an explicitly supplied HTTPX transport, streamed response
accounting, per-operation timeout extensions, retry-only connection/read failures,
429/5xx, and bounded jitter/Retry-After. Redirects are rejected outright; only
identity content encoding is accepted, preventing unbounded decompression.
Failed response bodies and partial reads count toward cumulative bytes. Deadlines
are checked around requests, streamed chunks, delays and consumer pauses; enforced
process-level termination and measured production budgets remain phase-6 work.

EIA requires its API key in the wire URL. Persisted request evidence omits it,
failures retain fixed safe diagnostics, and the transport context suppresses
pinned HTTPX/httpcore log records during request/read/close without changing
logger levels or suppressing unrelated threads. Real HTTPTransport fixtures
verify echoed response-header and exception secrets cannot reach those logs.
Imports construct no HTTP client and perform no network calls; bootstrap and
application authorization are unchanged.

Primary documentation consulted for the implementation:
[HTTPX streaming](https://www.python-httpx.org/quickstart/#streaming-responses),
[timeouts](https://www.python-httpx.org/advanced/timeouts/),
[transport injection](https://www.python-httpx.org/advanced/transports/), and
[EIA API requests, echoes and pagination](https://www.eia.gov/opendata/documentation.php).
These document library/general API behavior, not route-specific live guarantees.
AC3 live pagination, Q3/Q4 ordering/contract applicability beyond the bounded
baseline, hard runtime limits, maximum production interval, S3/RDS publication,
Admin authorization and initial live loading remain later gates. EC2 provisioning
is not required for these local checks.
