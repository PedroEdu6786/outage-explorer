# Outage Explorer — Decision Records

Status: initial recommendation followed by shared-deployment correction D10 and user-selected single replica D11. Tool/hosting mechanisms remain proposals. No ADR is accepted by this document.

## Round 1 — critic ledger

All three non-author critics steelmanned each proposal before objecting. Their common recommendation was A's application/containment design with C's early exploration demonstration, subject to the following revisions. B's same-parser advantage remains credible but does not itself prove authorization.

| ID | Target | Severity | Objection and smallest required revision | Status |
|---|---|---|---|---|
| D1 | A/B/C | Major | Engine/parser choice: B reduces interpretation mismatch but adds another toolchain; measure authorization/breadth rather than assume either wins. | Consensus recommendation; dissent retained |
| D2 | A/B/C | Blocking contract | Define refresh interval replacement, outside-interval preservation, completeness checks, removed rows, and source ambiguity; local atomic publication cannot claim upstream simultaneity. | Revised; source proof remains gate |
| D3 | A/B/C | Blocking contract | Bind pagination to generation/dataset/filter/order and expiry, authorize each page, retain input generations for query/cursor lifetime; reproduce pinned findings after refresh/cleanup. | Revised; acceptance added |
| D4 | A/B/C | Blocking contract | Define persisted refresh states, disconnect/restart behavior, duplicate/retry/concurrent calls, and who owns cancellation. Sync/async must be explicit. | Revised to async local ownership |
| D5 | A/B/C | Blocking readiness | Bound aggregate machine usage: worker admission, CPU/memory/output/deadline/cleanup, refresh budget and staging disk; host/runtime assumptions and measured tests required. | Design explicit; runtime/measurement pending |
| D6 | A/C | Major | Complete query authorization must precede opening analytical inputs or planning user-derived SQL. | Revised |
| D7 | A/B/C | Major | Audit all AST/operator/function paths, CTE shadowing/unused bodies, nested expressions and identifier forms; verify combinations of supported syntax rather than only isolated examples. | Revised; feasibility gate retained |
| D8 | A/B/C | Major | Apply role policy and safe errors across every endpoint, not just SQL; protect catalog, preview, metric and refresh diagnostics. | Revised |
| D9 | A/B/C | Major sequencing | Early source gate requires >=30-day actual extracts, a reconciliation probe and three candidate real findings before full backend commitment. | Revised |

## Attributed objections retained
- **ponykiller (Infra / SRE), D2:** “Atomic publication guarantees local completeness, not authoritative interval replacement or a point-in-time EIA snapshot.” Scenario: upserts preserve vanished rows and changing source pages can manufacture an apparent anomaly. Record per-route retrieval windows and distinguish source observations from a transactional snapshot.
- **ponykiller (Infra / SRE), D3:** “Pin pagination tokens” lacks a bounded lifecycle. Indefinite retention exhausts disk; early deletion breaks later pages.
- **ponykiller (Infra / SRE), D4:** “Durable run IDs do not specify what survives disconnect or process restart.” Define recovery rather than add a queue by implication.
- **estebanquito (Engineering Manager), D2:** “Publication is specified, but the refresh contract still cannot determine the expected resulting dataset.” Revised, removed and partial records need distinct acceptance cases.
- **estebanquito (Engineering Manager), D9:** “Source feasibility” lacks an evidence exit, allowing required anomalies to become a late surprise after substantial backend work.
- **cuid (Risk & Verifiability), D6:** “The design should explicitly place complete SQL authorization before opening query inputs or submitting any user-derived SQL to the engine.”
- **cuid (Risk & Verifiability), D7:** “A restrictive validator can satisfy denials while silently defeating the promised exploratory SQL.” Publish the surface and test compositions.
- **cuid (Risk & Verifiability), D8:** “Worker isolation does not by itself establish the Viewer promise for catalog, preview, metric, and error responses.”

## User-confirmed scope
- Challenge-only seeded database accounts suffice; no account lifecycle product requested.
- Broad read-only SQL includes joins, CTEs, subqueries, aggregations and windows over authorized analytical datasets.
- No predefined Analyst investigations; mandatory delivered findings remain.
- Timeline is not a constraint for this discussion; frontend remains deferred.

## D1 — Recommend Python/DuckDB/SQLGlot subject to proof
- **Context/options:** A/C's cohesive Python toolchain versus B's Rust/DataFusion single-parser/planner approach. FR9/FR10 and live explainability govern the choice.
- **Arguments for A/C:** rafachafa/kings — one data/API toolchain, no independent need for Rust, identical authorization/breadth proof burden applies to both.
- **Arguments for B:** gamachiel — removes a specific parser interpretation mismatch and offers explicit catalog/planner control.
- **Verdict:** Consensus recommendation A+C, with B available if feasibility fails. Do not build both full implementations merely to compare.
- **Who ticked:** gamachiel: “tick tick tick.” rafachafa/kings also conceded that the preference is conditional, not proven by tool selection.
- **Dissent (verbatim, gamachiel):** “A dual-parser design carries an ongoing compatibility obligation that container isolation does not discharge: FR10 requires rejection before execution, even when forbidden access would fail inside the worker. Revisit DataFusion if the pinned SQLGlot/DuckDB combination cannot demonstrate that contract without narrowing FR9.”
- **Revisit trigger:** Candidate cannot validate/reject consistently while preserving composed analytical SQL; or live runtime/toolchain evidence changes the comparison.

## D2 — Replace a validated requested interval
- **Context/options:** Upsert/merge, whole configured-period rebuild, or explicit interval replacement. Vanished records require a stated policy.
- **Arguments:** ponykiller/estebanquito demanded checkable outcomes; all authors revised to replace inside an inclusive interval and preserve outside it, after complete verified extraction.
- **Verdict:** Consensus proposed interval replacement with removed counts, retained raw evidence, route retrieval windows and conservative failed publication under unresolved extraction ambiguity. No promise of upstream point-in-time consistency.
- **Who ticked:** All three authors: “tick tick tick.”
- **Dissent:** None remaining; source behavior is still unknown.
- **Revisit trigger:** EIA cannot support a reliable interval extraction contract, or volume makes bounded full-coverage rebuild more defensible.

## D3 — Finite cursors and retained evidence
- **Context/options:** Current-only reads, indefinite version retention, or finite page leases plus separately pinned findings.
- **Arguments:** ponykiller/estebanquito identified skipped pages and unreproducible findings; gamachiel required dependency/transform versions as well as a snapshot ID.
- **Verdict:** Consensus finite principal-bound cursors with original fixed expiry, query leases, coordinated reference acquisition/cleanup, and separately retained exact evidence inputs/versions. Proposed cursor implementation is opaque state in SQLite; signed cursors remain an unselected equivalent alternative.
- **Who ticked:** All three authors: “tick tick tick.”
- **Dissent:** None remaining.
- **Revisit trigger:** Actual retention budget or multi-instance requirements make the simple local lease model insufficient.

## D4 — Application-owned asynchronous refresh
- **Context/options:** C's synchronous request, unspecified A mode, or B's background run.
- **Arguments for synchronous (original kings proposal):** “Recommend a synchronous Admin refresh for an explicit date interval, serialized to one run.” It offered a simple direct result for a potentially small workload.
- **Arguments against:** rafachafa/gamachiel — cancellation after publication but before outcome makes request-owned refresh ambiguous; ponykiller required restart and retry semantics.
- **Verdict:** Consensus recommendation `202` + persisted run/polling, one local application-owned run, explicit idempotency and restart/interruption contract. Durable generation files precede a SQLite transaction committing active pointer and success together. No broker or separate network service.
- **Who ticked:** kings: “tick tick tick.” All authors conceded their original lifecycle detail was insufficient.
- **Dissent (original rationale preserved):** “Synchronous execution could remain sufficient for a measured small workload.” — ponykiller's initial steelman of C. No active dissent after explicit ownership was accepted.
- **Revisit trigger:** User preference or measured small refresh workload warrants synchronous waiting on an independently owned durable run; slow/multi-instance workloads require another design discussion.

## D5 — Explicit confinement and aggregate budget
- **Context/options:** Engine/parser checks alone, ordinary subprocess, or constrained local container. All authored proposals independently chose container containment; there was no manufactured split vote.
- **Arguments:** cuid required independent isolation; ponykiller/estebanquito challenged unspecified host and aggregate resources. Docker docs and DuckDB guidance establish capabilities, not tested configuration.
- **Verdict:** Consensus proposed disposable role-scoped container, bounded query/refresh admission, physical checks and measured aggregate memory/disk/headroom. Numerical values are benchmark candidates and Docker remains a user/runtime question.
- **Who ticked:** All authors conceded missing detail: “tick tick tick.”
- **Dissent:** No active design dissent. Runtime availability and startup cost remain unresolved facts, not accepted risk on the user's behalf.
- **Revisit trigger:** Host lacks the runtime, confinement cannot be verified, or performance/resource gates fail.

## D6 — Authorization before every analytical access
- **Context/options:** Complete validation before bootstrap versus allowing bootstrap/planning before all references are checked.
- **Arguments:** cuid identified mixed authorized/forbidden statements violating the pre-access contract even if sandbox later blocks disclosure; B already stated the stronger ordering.
- **Verdict:** Consensus authenticate → parse/resolve/authorize entire AST/functions without analytical reads → worker/bootstrap → execute validated statement. Instrument this order.
- **Who ticked:** rafachafa/kings: “tick tick tick.” gamachiel retained B's existing ordering.
- **Dissent:** None.
- **Revisit trigger:** Any new SQL/provider feature changes pre-execution resolution.

## D7 — Prove breadth and rejection together
- **Context/options:** Denial tests alone versus positive composed-query tests plus negative access corpus.
- **Arguments:** cuid/kings warned that a restrictive validator can make broad SQL nominal rather than usable; gamachiel added exact generated-statement validation and pinned compatibility.
- **Verdict:** Consensus documented syntax/function/operator surface, full traversal and composed FR9 examples with independently checked results. Recursive CTE handling remains an explicit open decision; it was not silently excluded from user intent.
- **Who ticked:** All authors: “tick tick tick.”
- **Dissent:** Dual-parser concern remains under D1.
- **Revisit trigger:** Any dependency update or new analytical form/function.

## D8 — One policy across product paths
- **Context/options:** SQL-only boundary versus common role policy across catalog, preview, metric, SQL, cursors and run diagnostics.
- **Arguments:** cuid identified metadata/error side paths; authors accepted the common policy and safe diagnostics.
- **Verdict:** Consensus endpoint-level authorization before data access, Admin-only run metadata, direct-request tests and protected error responses.
- **Who ticked:** All authors: “tick tick tick.”
- **Dissent:** None.
- **Revisit trigger:** New endpoint, export, cache or frontend-driven backend path.

## D9 — Source and SQL feasibility before full backend commitment
- **Context/options:** C's early exploration slice versus mandatory data/findings evidence discovered only late.
- **Arguments:** estebanquito required >=30-day real extracts, reconciliation and three evidenced candidate anomalies early; kings retained the useful exploration slice after that gate and in parallel with a limited SQL spike.
- **Verdict:** Consensus two early independent gates: source evidence and SQL/isolation feasibility. Then build authenticated free exploration and complete final findings. No invented anomalies or silent scope shrinkage.
- **Who ticked:** All authors: “tick tick tick.” estebanquito conceded the revised plan resolves his blockers: “tick tick tick”.
- **Dissent:** None.
- **Revisit trigger:** Either gate fails; explicitly reopen its requirement/approach rather than continue as if verified.

## Round 2 — convergence and verification limits
- cuid: “Convergence: no remaining blocking design objections.”
- ponykiller: “Convergence: no remaining blocking operational design objection.” Added coordinated reference acquisition/cleanup and nonrenewing expiry acceptance, now folded into the plan.
- estebanquito: “No remaining blocking design flaw from the delivery/acceptance seat.” Required keeping user decisions, empirical gates and implementation acceptance distinct.
- No third round needed. User pushback should trigger a focused mini-debate rather than silently altering these decisions.
- Source/model investigation, runtime confirmation, quantitative limits and tested SQL compatibility are still pending. Council convergence means a reviewable recommendation; it does not establish that code exists or that the challenge is complete.

## D10 — User correction: backend-owned data and realistic shared deployment
- **User direction:** “we need to scale it as an accurate app deployment/development, the parquet stored locally could be reffered to stored on our own backend service, that provides availability to all users”.
- **Context:** The Chair's follow-up explanations and initial plan over-narrowed the challenge to a developer laptop. Seeded accounts did not authorize that deployment restriction.
- **Mini-debate:** ponykiller (Infra), gamachiel (Architect), and kings (Product) independently reviewed updated FR16/TR7/TR8/AC13. All conceded the earlier assumption; “tick tick tick” from each. No dissent about the corrected scope.
- **Verdict:** User-confirmed: backend-owned persistent data serves all authorized clients; development must reproduce a realistic deployed service. Retain role boundaries, seeded accounts, broad read-only SQL and frontend deferral.
- **Requirements versus choices:** Shared users do not by themselves select multiple API replicas, object storage, a cloud vendor, managed identity or uninterrupted deployments. One durable coordinating instance and multiple replicas with shared storage/state remain alternatives pending the user's topology answer.
- **Consequences:** Reopen SQLite metadata, local mounts, single-process refresh ownership/admission, and local Docker launching. These are conditional single-owner mechanisms, not deployment-neutral guarantees. All topologies must retain data/operational state across API/query replacement and keep storage credentials out of user SQL execution.
- **Preserved constraint:** gamachiel — “We can add replicas later” cannot silently preserve single-host assumptions. Establish the chosen storage/publication/ownership contracts before dependent implementation; do not implement multiple adapters before selecting topology.
- **Acceptance:** Separate clients see the common published generation under their roles. Replace backend/query containers with EIA unavailable, then verify data, accounts, evidence and recoverable publication/refresh state. Session survival/relogin behavior is declared explicitly.
- **Open decision:** One backend instance with durable storage or multiple replicas with shared coordination (asked asynchronously); acceptable restart/deployment interruption and hosting follow. No topology or provider selected and no deployment performed.
- **Source checks:** [Docker volumes](https://docs.docker.com/engine/storage/volumes/) documents container-independent persistence; [SQLite WAL](https://www.sqlite.org/wal.html) documents same-host/network-filesystem limitations. These do not establish an availability SLA.

## D11 — User selected one backend replica for now
- **User direction:** “for now lets keep the scope into one replica”.
- **Verdict:** One active deployed backend replica serving all authorized users. Multiple replicas and horizontal autoscaling are deferred until an explicit capacity/availability requirement reopens them.
- **Options resolved:** Select the single-backend branch of D10; the multi-replica alternative remains historical context, not current implementation scope.
- **Tool impact:** Persistent attached storage, SQLite users/session/run metadata and an application-owned refresh coordinator remain suitable proposals to evaluate. No cross-replica metadata service, distributed publisher/lease coordination or distributed queue is required by current scope. DuckDB/SQLGlot analytics and pre-access authorization/isolation obligations do not change.
- **Not implied:** One user, one concurrent request, one API process, one query worker, SQLite acceptance, a cloud provider, Docker acceptance, a specific storage product or an availability SLA. Internal ownership/admission and replacement behavior must still be explicit.
- **Deployment consequence:** Preserve data/state across replacement and prevent overlapping active backend owners; interruption behavior is still to be documented, not promised as zero downtime.
- **Dissent:** None; this is the user's selection among already examined options, not a new council vote.
- **Revisit trigger:** User requests horizontal scale or continuity/capacity goals requiring more than one backend replica.

## D12 — User accepted separate object storage for Parquet
- **User direction:** After requesting persistent Parquet storage, the user accepted the object-storage recommendation: “the decision is fine”.
- **Verdict:** A separate application-owned object-storage bucket is Parquet's durable home. One backend replica remains the selected topology; provider/hosting is still open, with S3 conditional on AWS.
- **Proposed query flow:** The trusted backend authorizes the whole query, pins one published snapshot, and stages only permitted manifest-listed objects. An isolated DuckDB worker materializes named in-memory tables before external access is disabled and user SQL executes. Bucket credentials stay outside that worker. Staging is disposable; the bucket remains authoritative.
- **Publication:** Upload and verify an immutable generation before committing its active pointer and refresh success in operational metadata. Failed uploads never become visible as the current snapshot.
- **Limits:** Operational metadata still needs separately durable storage; a bucket does not host an active SQLite database. Per-query loading cost and memory budgets require measurement. EIA-independent reads still depend on availability of the selected object storage.
- **Dissent:** None newly raised; selection narrows the storage alternatives already examined. Worker runtime, full stack and provider are proposals, not newly approved tools.

## Follow-up — Alternatives to the S3/Parquet/DuckDB flow (no selection)
- **Question:** User asked whether an “open better solution” exists; open-source storage versus overall architecture is not yet clarified.
- **Mini-debate:** rafachafa and cuid support retaining object-storage Parquet plus DuckDB for the current scope. Both recommend measuring repeated transfer/materialization costs before introducing a reusable immutable snapshot cache. rafachafa reported no blocking objection to cuid's qualifications.
- **Alternatives:** Cached Parquet requires tested exact-file access for trusted views; blanket external-access denial prevents those reads. Derived read-only DuckDB snapshots avoid repeated materialization but add a rebuildable serving representation per permission tier. Both require generation pins, bounded eviction, full pre-access authorization and isolated workers without bucket credentials/network.
- **Status:** These are optional measured optimizations; cache remains deferred and no plan requirement or accepted storage decision changes. An open-source S3-compatible service such as SeaweedFS is a provider alternative, not a persistence guarantee; durable disks and operations remain necessary. No provider was selected.

## D13 — Record Amazon S3 + Parquet + DuckDB as the selected combination
- **User direction:** After the comparison with persistent-disk-only DuckDB, the user requested “keep this decisions documented on the project” and confirmed “ignore the decisions file ruling, adr is fine”.
- **Decision:** Amazon S3 is the durable home for raw/modeled Parquet; DuckDB executes analytical SQL; one active backend replica remains the topology. [ADR-0001](../../../adr/0001-s3-parquet-duckdb.md) is the accepted decision record with context, alternatives and consequences.
- **Rationale:** Preserve the required analytical artifacts independently of backend replacement while using an embedded analytical engine. A persistent DuckDB database would still require durable underlying storage and would not replace the required Parquet artifacts.
- **Still open:** Backend hosting, S3 configuration, operational-state persistence, exact SQL validation/isolation and remote reads versus staged execution. Reusable snapshots remain a measured optimization, not selected scope. This does not accept the rest of the council stack or provision infrastructure.
- **History:** D12 records acceptance of the storage category; D13 resolves its previously open provider and the analytical engine. Earlier alternatives and parser dissent remain historical evidence and revisit triggers.
