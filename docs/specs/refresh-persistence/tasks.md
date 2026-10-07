# Tasks: Three-file refresh persistence optimization
> Status: phase 1 complete; phases 2–4 pending · Slug: refresh-persistence · Plan: ./plan.md · Spec: ./spec.md

## Overview
- 25 implementation/test tasks + 4 checkpoints = 29 tasks across 4 plan phases; 6 tasks parallelizable [P].
- [Phase 1](tasks/phase-1.md): local candidate contracts, unified files and transient quality — complete; T1.1–T1.8 and T1.C passed, with shared composition switch deferred to phase 4.
- [Phase 2](tasks/phase-2.md): bounded three-file persistence/readback — depends on T1.C.
- [Phase 3](tasks/phase-3.md): PostgreSQL publication and direct analytical cache — depends on T2.C.
- [Phase 4](tasks/phase-4.md): refresh/CLI composition and controlled end-to-end verification — depends on T3.C.
- All paths are repository-relative; only the explicitly marked migration path is new. Recheck concurrent changes and migration head before implementation; preserve unrelated work, historical ADRs, fixtures and append-only devlog.
- [P] siblings may overlap only after their named common prerequisite; every other task is ordered by its explicit dependencies. Checkpoints block advancement. Phase 1 proves the new local pipeline through explicit injection and preserves existing consumers; durable/product integration remains phase 2–4 acceptance.

## Approval and contract gates omitted from the plan
- **G1 — resolved October 6, 2026:** User explicitly accepted ADR-0060 and authorized required repository-guidance synchronization. ADR-0042 complete-graph replay and ADR-0057 six-file/audit-preservation clauses are superseded. Runtime activation is not authorized.
- **G2 — resolved October 6, 2026:** User approved retaining the existing modeled physical codec's provenance, original numeric strings, units, natural identity and exact calculation evidence privately inside the three unified resource files. Preserve `ModeledRow.observation.original` and `Origin` without synthesis or precision loss; analytical views expose only existing public columns under `national`, `facilities`, `generators` (grain identifiers are singular). No old-format conversion is introduced.
- **G3 — current-generation cutover, before T3.2 and runtime use:** the plan assumes a fresh initial load but specifies no authorized transition for an existing active six-file/manifest generation. Obtain a history-preserving schema rollout/cutover and rollback decision, including how existing published rows are read and how an incompatible active base fails closed. Do not backfill invented descriptors, reset `refresh_coordination.active_generation_id`, delete history/old S3 objects, add a reset CLI, or initiate a live load. ADR-0058 records a one-time direction, not standing permission.
- **G4 — object identity, before T2.2:** existing `S3ArtifactStore` maps logical digest keys to configured `objects/` keys; AC1/plan refer to a generation prefix. Confirm exact physical key mapping for three immutable files per generation, PostgreSQL descriptors and explicit recovery. Do not select a new layout silently or rely on bucket listing/HEAD to reconstruct descriptors.
- These are concrete missing plan decisions, not a replacement design. If their resolution changes the plan, stop for an updated approved plan rather than implementing a guessed contract.

## Cross-phase contracts
- **Sequencing correction authorized by the user:** Phase 1 builds the new local
  pipeline behind explicit three-resource interfaces; it does not switch existing
  CLI/refresh/bootstrap composition. Phases 2–3 prepare its durable consumers;
  phase 4 switches shared producers/consumers and removes obsolete graph APIs.
  New candidate construction writes exactly three files, never a second graph.
  Existing composed behavior remains regression-tested until that switch. No
  conversion or old-layout fallback is added to the new pipeline.
- T1.1 defines candidate/resource/receipt contracts before any service or adapter uses them; `CandidateResult`/`QualityReport` are proposed plan concepts, not existing APIs (`CandidateManifest`/`GrainSummary`/`Quality` exist today).
- T1.2/T1.5 provide the unified codec and sorted baseline iterator consumed by T2.5, T3.5 and T4.1; T1.6 supplies verified three-file candidates, never a caller-asserted verification flag.
- T2.2/T2.4 establish exact durable references and all-file readback receipts; T3.1 maps them into `DatasetSummary`; T3.4 commits only those references; T4.1 checks their identity against the verified candidate before publication.
- T3.2 preserves immutable historical records under G3; actual existing columns are `published_generations.datasets`, `manifest_key`, `manifest_digest` and `refresh_runs.quality_json`, not a fabricated `datasets_json` column.
- T3.5 preserves public-only views over exact staged files and authorization/isolation; T4.2 supplies concrete dependencies through bootstrap, never through Flask handlers.

## Verification discipline
- Each phase checkpoint lists AC obligations and the README/Makefile Ruff, format, mypy and pytest commands; execute them during implementation, not during this docs-only breakdown. Disposable PostgreSQL/browser prerequisites must already be available or be reported missing; never substitute RDS/live AWS/EIA for tests.
- Controlled SDK/HTTP transports, real local Parquet and isolated DuckDB tests establish behavior only. ADR-0060's ~4,326→9 operations and ~57.5→18 MB are estimates, not benchmark assertions, measured evidence or host-capacity guarantees.
- The user's subsequent direction authorizes Phase 1 implementation under resolved G1/G2. This list itself grants no source/cloud calls, runtime startup, deployment, deletion or publication reset. Repository commit conventions remain applicable after verification.
