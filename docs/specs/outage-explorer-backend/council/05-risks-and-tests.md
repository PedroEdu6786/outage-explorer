# Outage Explorer — Risks & Test Scenarios

Status: proposed safeguards and required verification, not evidence of implemented safety. See `03-decisions.md` for council concessions and remaining dissent.

## Edge cases
- **EC1:** Empty route or interval → preserve old publication until a source-backed empty-period policy permits replacement; don't silently label incomplete extraction successful. → FR1–FR3
- **EC2:** Duplicate natural key with identical or conflicting values → apply documented deduplication/validation policy, retain evidence, reject ambiguous conflict before publication. → FR2–FR3
- **EC3:** Missing parent or mismatched grain totals in otherwise valid source observations → preserve and expose to authorized analysts, record quality findings; do not enforce invented relationships. → FR2, FR13–FR14
- **EC4:** National metric denominator missing/zero or units differ → use the source-verified documented policy, never silently divide or fabricate capacity. → FR12
- **EC5:** CTE shadows a product table, unused CTE references forbidden detail, nested expression contains an external call, quoted/qualified identifiers obscure a relation → resolve complete supported syntax and reject before data/engine access. → FR6, FR9–FR10
- **EC6:** Individually supported analytical forms are composed in one query → return independently checked results within limits; security restrictions must not make advertised combinations unusable. → FR9
- **EC7:** Huge AST, recursive request, explosive join, very large value or tiny result from expensive work → bounded parse/execution/output with clear outcome and verified worker cleanup. Recursive SQL policy remains open. → FR9–FR10; TR3
- **EC8:** Refresh between preview pages → continue original generation until finite expiry, then explicit restart response. Wrong-principal/filter/tampered cursors never grant access. → FR6, FR8
- **EC9:** Source removes/revises a row inside the requested interval → validated replacement changes that interval only; preserve outside observations and historical evidence. Ambiguous coverage fails conservatively. → FR1–FR3, FR11
- **EC10:** Two Admin refreshes, identical retry or changed parameters with reused key → one active run; identical request returns same run; changed/conflicting request fails visibly. → FR11, FR15
- **EC11:** Client disconnect or restart around publication → application owns run, pointer and success commit atomically after durable files; unfinished unpublished run becomes interrupted. → FR3–FR4, FR11
- **EC12:** Cleanup after later refresh → keep active query/cursor references and all evidence pins; reproduce old findings using original versions. → FR8, FR13–FR14
- **EC13:** API/query process replacement while EIA is unavailable → reattach/recover backend-owned data and operational state; separate clients continue to see authorized common publication after declared recovery. → FR4, FR6, FR16; TR8

## Failure modes
- **FM1:** SQL parser/engine semantic disagreement → forbidden access accepted or legitimate query rejected → pinned versions, exact statement revalidation, adversarial/composition tests; revisit DataFusion if contract cannot be met.
- **FM2:** Restricted tables/files reach a Viewer worker → validation bug becomes disclosure → mount only role-permitted modeled inputs and inspect actual mounts; don't mount whole snapshot roots containing raw/detail data.
- **FM3:** Secrets leak through worker environment or raw engine diagnostics → product confidentiality fails → explicit environment allowlist, no credentials/identity DB/socket, safe structured responses, direct endpoint error tests.
- **FM4:** Container exists but shares host privileges/network/unbounded resources → false isolation claim → verify non-root/restricted privileges, read-only mounts/root, network denial, process/CPU/memory/scratch limits and kill/reap behavior.
- **FM5:** Query/refresh budgets individually pass but combined host memory/disk exhausts → existing local data becomes unavailable → single-slot admission, measured headroom/reserves, bounded staging and failed refresh retaining old publication.
- **FM6:** EIA changes while paginating/fetching routes → inconsistent source observations mistaken for a nuclear event → record retrieval windows and checks, investigate/repeat bounded retrieval where warranted; do not assert transactional source consistency.
- **FM7:** Generic data validation deletes real discrepancies → three-anomaly requirement becomes impossible or misleading → distinguish structural corruption from domain mismatches and retain raw evidence.
- **FM8:** Findings exist only against mutable current data or undocumented tooling → old result cannot be reproduced → pin files/hashes/queries/metric definition/transformation/dependency versions and test after refresh/cleanup.
- **FM9:** No three real anomalies established → challenge analytical gate unfulfilled → investigate before full backend build, report evidence gap, never invent examples or causes.
- **FM10:** Docker or proposed host limits unsuitable → setup/live session fails → runtime review and measured feasibility before dependent tasks; no unchecked in-process fallback.
- **FM11:** API replica sees its own snapshot/session/run state, or storage disappears with container replacement → shared clients get inconsistent results or lose ingested data → select persistent storage and a topology-appropriate publication/ownership/metadata contract before implementation. No local-file or process-lock assumption silently crosses host boundaries. → FR16; TR7–TR8
- **FM12:** Deployment allows an old refresh owner to publish after replacement, or replica startup marks another live run interrupted → incorrect active dataset/outcome → single-owner replacement exclusion or shared ownership with stale-owner protection, depending on selected topology. → FR3, FR11, FR16; TR8

## Key test scenarios
- **TS1:** Given mocked multipage source data, when extracting all three routes twice, then count/key coverage is complete and no duplicate published keys appear. Also verify actual source pages during investigation. Covers FR1–FR3, AC1–AC2.
- **TS2:** Given one valid generation, when upstream is unreachable, then authorized catalog, preview, metric and SQL succeed without EIA calls. Covers FR4, AC3.
- **TS3:** Given seeded roles, when directly calling every API with valid/invalid/expired/forged credentials, then identity and permission outcomes match the matrix before data access. Covers FR5–FR8, FR10–FR12, FR15, AC4–AC5.
- **TS4:** Given a query combining CTEs, joins, correlated subqueries, aggregation and windows, when an Analyst submits it, then returned values match an independent calculation. Repeat equivalent national-only composition as Viewer. Covers FR9, AC7.
- **TS5:** Given disallowed tables/functions in used and unused scopes and every identifier form, when submitted, then instrumentation proves no analytical input opened, no worker launched, no user-derived engine plan executed. Covers FR6, FR10, AC8.
- **TS6:** Given an isolated worker, when adversarial SQL targets external files/network/extensions/metadata or resource exhaustion, then policy rejects before execution where applicable, sandbox remains constrained, and deadline termination reaps the worker. Positive broad SQL must still pass in the identical runtime. Covers FR6, FR9–FR10, AC7–AC8.
- **TS7:** Given a preview cursor, when refresh publishes and cleanup runs, then continuation uses its original snapshot until expiry, then returns explicit expiry. Altered identity/filter and forged cursor fail. Covers FR6, FR8, AC6.
- **TS8:** Given source revisions/removals, when refreshing an inclusive interval, then validated changes replace only that interval; missing pages, instability or unsupported empty coverage leave the old generation current. Covers FR1–FR3, FR11, AC2/AC9.
- **TS9:** Given running refresh, when a client disconnects or retries, then one persisted outcome remains; crash injection before/after pointer transaction yields published success or unpublished interruption without mixed state. Covers FR3–FR4, FR11, FR15, AC9.
- **TS10:** Given real verified metric input and edge cases, when computed, then the national ratio agrees with independent arithmetic and documented null/zero treatment. Covers FR12, AC10.
- **TS11:** Given three actual findings across >=30 days, when current data changes and ordinary cleanup runs, then original evidence remains reproducible from pinned versions; actual values and hypothesis labels remain documented. Covers FR13–FR14, AC11.
- **TS12:** Given a clean supported host, when setting up and running query+refresh under resource pressure, then setup/docs are sufficient, total budgets hold, and source/evidence commands work. Covers TR3–TR4, TR7, AC12.
- **TS13:** Given one backend ingestion and independent Viewer/Analyst clients, when API/query containers are replaced with EIA blocked, then backend-owned snapshots, permissions/accounts, evidence and recoverable publication/run state remain available after declared recovery; clients need no files or EIA key. Covers FR4, FR6, FR16, TR8, AC13. Multiple-replica tests are conditional on topology selection.

## Accepted risks
These are council-proposed tradeoffs, not user-approved production risks:
- **D1:** The Python/DuckDB/SQLGlot path has an ongoing compatibility obligation. gamachiel's dissent remains verbatim in the decision record; reopen if feasibility fails.
- **D2:** A local generation can be atomically published without proving EIA was observed at one instant. Expose retrieval provenance; don't invent certainty.
- **D3:** Cursor expiry deliberately requires a new preview after the finite window to bound retention. Evidence pins are retained separately.
- **D4:** Background refresh adds durable local run state; restart interrupts rather than resumes source retrieval automatically.
- **D5:** Disposable query containers add startup overhead and a Docker dependency; host and performance acceptance remain open.
- **D10 supersedes laptop-only scope:** All earlier host/runtime/metadata mechanisms are conditional. Shared backend deployment is required; provider, replica count, storage implementation and availability/interruption target remain undecided. Durability does not imply zero downtime or protection against infrastructure loss.
- No untested parser, sandbox, source field, actual anomaly, or resource default is represented as verified by this planning exercise.
- **D11 current topology:** User selected one active backend replica. Multi-replica tests/coordination above are deferred revisit notes; current acceptance checks separate clients, shared data, replacement without overlapping backend owners, and coordination across any internal processes. Replica count does not determine query concurrency. Storage/runtime/provider and interruption expectations remain open.
- **D12 current storage:** User accepted an independent object-storage bucket for Parquet; provider and operational-state persistence remain open. Test failed/partial uploads before publication, manifest integrity, role-limited staging, absence of bucket credentials/network in user SQL execution, and container replacement without EIA re-ingestion. Measure object download and in-memory load costs within request budgets. Bucket availability is still required for uncached reads.
- **D13 latest selection:** Amazon S3 + Parquet + DuckDB is now recorded in ADR-0001; the provider-open note in D12 is historical. Staging-specific checks apply to the proposed worker path. Final remote-read/staging selection must preserve authorization/isolation and pass performance/resource checks; no runtime result is established by documenting this decision.
