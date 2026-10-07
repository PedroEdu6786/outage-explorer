# Refresh persistence optimization — Decision Records

These are planning recommendations, not new accepted ADRs or runtime acceptance.
Two original rounds concluded with no blocking objections; no implementation tests ran.
The subsequent user-directed three-file scope revision reopens the storage design
and supersedes the concurrency-first/evidence-preservation conclusions below.

## D5 — Three resource files, no persisted supporting evidence
- **User direction:** "just storing the 3 resource files is fine, storing additional
  data is stupid, this needs to get contemplated on this effort" and confirmed
  "this is ok, its better this way, add this into the scope of the specs already created".
- **Scope verdict:** Storage reduction is formally incorporated into the effort via
  ADR-0060 (Proposed). Exactly three resource Parquets per generation in S3; eliminate
  persisted raw/page/disposition/ledger artifacts and duplicate public/model
  representations.
- **Challenge requirements alignment:** Re-verified against challenge PDF criteria.
  No challenge requirement mandates retaining discarded invalid records, duplicate
  conflict history, or raw pagination metadata across arbitrary past runs.
  Challenge anomaly evidence (Finding 001) is preserved in repository test fixtures
  and documentation.
- **Metadata placement:** Essential exact-file publication references (keys, SHA-256,
  byte count, row count) reside in PostgreSQL `published_generations`. No separate
  S3 manifest object is persisted.
- **Assurance model:** Transient verification during merge walk evaluates source
  normalization, validity filtering, and duplicate handling in local staging.
  Aggregated quality statistics are committed to PostgreSQL `refresh_runs.quality_json`
  under ADR-0025. Durable persistence verification performs SHA-256 readback on the
  three resource files.
- **Accepted boundary change:** Drafted ADR-0060, superseding the 6-file and
  audit-preservation clauses of ADR-0057 and full-evidence replay of ADR-0042.
- **Status:** Unblocked. Spec and plan are updated to the 3-file model and ready for
  `/tasks`. No deletion of historical S3 data or history rewrite is authorized.

## D1 — Optimization before a baseline study
- **Context:** The October 5 proposal gated tuning/default changes on measurements.
  The user explicitly requested code improvements first, estimating ten minutes.
- **Options considered:** retain measurement-first; optimize supported code seams.
- **Arguments for:** kings (Product) and estebanquito (Engineering Manager) — the
  baseline project delays the value requested; deterministic overlap/correctness
  tests can establish removal of serialization without a wall-time promise.
- **Arguments against:** historical proposal required measured matched workloads
  before selecting configuration; no current persona defended that as a blocker.
- **Verdict:** User-directed optimization-first, by consensus. Record performance
  as unmeasured; no fixed numerical target, new progress contract or benchmark gate.
- **Who ticked:** None; this is user steering, not an invented contested vote.
- **Dissent (kept):** None from the seated council.
- **Revisit trigger:** User requests quantified speedup or further tuning.

## D2 — Existing concurrency first; defer broad verification reuse
- **Context:** Both authors propose admitted default 3 and both-direction wiring;
  B adds a verifier-owned proof contract, A identifies one narrow replay cut.
- **Options considered:** A; B with scoped graph proof; concurrent delivery followed
  by an independent narrow equivalence checkpoint.
- **Arguments for:** rafachafa (Pragmatist), kings (Product), estebanquito
  (Engineering Manager) — concurrency already exists; proof-contract/mutation
  machinery need not delay delivery. cuid (Risk) requires complete ancestry and
  conflict/accounting checks before any future proof could be minted.
- **Arguments against, kept verbatim:** gamachiel (Architect) —
  "Introduce an ephemeral, verifier-owned local graph result containing verified
  manifest and exact dependency closure, bound to store session, root identity,
  bounds, and verification contract. Refresh identity checks and persistence are
  its two concrete consumers: today `refresh_execution.py:128–141` performs graph
  replay plus reopening, followed by another replay in `connector_artifacts.py:55–57`."
- **Verdict:** Revised A, consensus after B concession. First release passes
  AC1–AC4/AC6; optional post-prior-restore graph removal independently passes AC5
  or remains unchanged. Broader semantic reuse is excluded from this plan.
- **Who ticked:** gamachiel — "tick tick tick — I concede the proof-result contract
  adds delivery scope unnecessary for the first useful release".
- **Dissent (kept):** The original reuse argument above remains a future option;
  no unresolved blocker after concession.
- **Revisit trigger:** Explicit further replay-optimization scope identifying
  exact traversals to remove and mutation/ancestry checks to preserve.

## D3 — Logical payload admission is not host-capacity proof
- **Context:** Both initial proposals reused CLI calculations for HTTP admission.
- **Options considered:** describe the formulas as total capacity assurance;
  explicitly adopt logical checks and retain a separate residency inventory.
- **Arguments for:** ponykiller (Infra) — formula omissions include manifests,
  metadata, Python/Arrow/day state and other on-disk occupants; CLI values were
  not already enforced HTTP allowances.
- **Original blocking objection, kept verbatim:** "The copied CLI equations do
  not establish a complete HTTP persistence memory envelope, and M/T are not
  already-enforced HTTP allowances."
- **Verdict:** Both authors conceded. Document new HTTP logical preflight,
  transfer/replay residency, exclusions and unchanged shared runtime counters;
  do not claim RSS/filesystem containment. Default 3 is an initial recommendation.
- **Who ticked:** rafachafa and gamachiel conceded the capacity claim; ponykiller
  subsequently stated "tick tick tick — the blocking resource objection is
  resolved under TR2’s logical-admission interpretation."
- **Dissent (kept):** Whole-host capacity is still unproven; it is a recorded
  limitation rather than a new prerequisite benchmark or invented measurement.
- **Revisit trigger:** Memory pressure, disk exhaustion or changed file/graph bounds.

## D4 — Lifecycle and compatibility revisions required by review
- **Context:** Existing scheduling, HTTP composition and persisted JSON create
  failure cases beyond changing a worker-count integer.
- **Options considered:** integer-only wiring; explicit lifecycle/compatibility
  contract within the same existing boundaries.
- **Arguments for:** gamachiel (Architect) — persistence needs its own evidence
  view so download workers do not remain serial or inherit candidate time.
  kings (Product) — exercise actual HTTP composition, not only the scheduler.
  cuid (Risk) — own/close streaming iterators before task completion, and reject
  malformed snapshots after claim rather than poisoning history reads.
  ponykiller (Infra) — thread joining is cooperative; rollback readers must
  understand the persisted new field even for terminal history.
- **Verdict:** Consensus; adopt all revisions. One run cancellation signal,
  separate stage absolute deadlines, bounded wait polling, task-owned stream
  cleanup, joins before shared cleanup, frozen config and compatible rollback.
- **Who ticked:** rafachafa/gamachiel accepted the revisions; cuid's final verdict:
  "tick tick tick — the revisions resolve my lifecycle and configuration
  objections; deferring proof-result reuse removes that concern from this scope."
- **Dissent (kept):** ponykiller's remaining major availability risk: "Indefinitely
  blocked I/O remains a major availability risk, not a hard-termination guarantee:
  cancellation stops admission but cannot guarantee timely join."
- **Revisit trigger:** A hard termination requirement or observed stuck-I/O failure
  demands a separately scoped solution; no such guarantee is invented here.

## Changes to the existing proposal and over-engineering audit
- Canonical artifacts now live at `docs/specs/refresh-persistence/`; the old note
  remains as historical evidence and links here for current sequencing.
- Measurement-first/default-1-until-measured are replaced by the user's
  optimization-first direction and proposed default 3, with 1 preserved.
- New decisions make frozen configuration, both transfer directions, lifecycle
  ownership and real composition tests explicit; no public API/format changes.
- Broad proof reuse, CPU pools, multiple owners, compaction, progress reporting,
  and measurement infrastructure were cut or deferred with spec revisit triggers.
- Every retained component serves FR1–FR7 or preserves TR2–TR5; no file-level task
  list, runtime activation, acceptance ADR, commit or implementation is implied.
