# Small-team analytical runtime — Decision Records

These are Chair's recommendations for the assessment, not new accepted product
decisions. Users must accept any changed boundary before implementation.

## D1 — Compare services before building concurrent runtime machinery
- **Context:** The current evidence measures neither completed SQL nor service capacity. Local Docker evidence exists, but it does not answer cost/operation fit. MotherDuck, Athena and Fargate alter different parts of execution and result contracts.
- **Options considered:** Keep building local Docker first; replace it immediately; compare contracts/operations first, then select an authorized experiment.
- **Arguments for:** kings (Product) — “Existing code is evidence about migration effort, not a reason to prefer Docker.” gamachiel (Architect) — service contracts, input/output ownership, authorization and cancellation must be compared before deciding.
- **Arguments against:** rafachafa (Pragmatist) — existing Docker isolation evidence and the straightforward metadata problem make it a low-cost leading candidate.
- **Verdict:** Complete source-backed capability/contract/operation/cost-driver comparison before implementation of a concurrent pool. Preserve DuckDB+Docker as the leading candidate for evaluation, not a selected outcome. This order limits sunk cost and does not claim a service is better.
- **Who ticked:** None. Consensus on ordering; no engine/service decision is settled.
- **Dissent (kept):** rafachafa's “useful real synthetic-denial evidence” lowers the cost of checking a local option but does not answer whether its long-term operator burden is acceptable.
- **Revisit trigger:** A documented comparison finds an alternative with a clear fit advantage and a separately authorized way to test its decisive unknowns.

## D2 — Evaluate one sealed request-directory mount
- **Context:** Current preparation already copies verified inputs into a fresh private execution directory. Docker launch arguments then include one bind per file. The 549-file request exceeded the controller argument bound before any container was created.
- **Options considered:** Increase argument bound as an ongoing design; retain per-file mounts; bind the exact sealed request directory once; change data partitioning/service.
- **Arguments for:** rafachafa (Pragmatist) — constant Docker mount count addresses measured metadata amplification while reusing DuckDB and avoiding publication changes. gamachiel (Architect) — exact request-owned directory keeps shared cache/siblings outside the worker boundary.
- **Arguments against:** cuid (Risk & Verifiability) — a read-only bind alone does not prove the source directory is the same verified inode/content set at use time.
- **Verdict:** Recommend a **single-worker bounded experiment** for one exact private directory bind with exact-entry, identity, mutation and nested-mount safeguards. Keep per-file argument enlargement as a separate diagnostic option only. Manifest, digest checks, staging bytes and file scans still grow with input count.
- **Who ticked:** cuid — “tick tick tick” — after the authors made exact entries, private parent, inode lifetime, mutation/path-reuse restrictions and recursive-bind rejection explicit; these remain acceptance conditions, not claims of implementation success.
- **Dissent (kept):** The candidate could still require special path permissions or have daemon-specific nested-mount semantics. If those cannot be proven on the selected Linux host, reject it and revisit a service/format option.
- **Revisit trigger:** Directory race, source replacement, sibling/cross-request exposure, unsupported daemon behavior, or measured preparation overhead that remains unacceptable.

## D3 — Treat 2/4 concurrency and per-lane ext4 as experiments
- **Context:** `VerifiedLauncher` admits one execution; the finite spill adapter exclusively locks its entire filesystem. Simply changing a semaphore neither assigns independent spill ceilings nor accounts for concurrent host preparation/control.
- **Options considered:** Keep one slot; increase its count; fixed independent lanes; project quota/shared storage; managed workers/service.
- **Arguments for:** gamachiel (Architect) — slots need aggregate host ceilings plus per-lane ownership and daemon-wide reconciliation. ponykiller (Infra) — “Finite filesystem capacity does not establish physical backing availability.” Per-lane ext4 may be overcommitted if several images share one thin backing disk.
- **Arguments against:** A fixed local pool reuses current lifecycle/isolation work and avoids adding a queue/broker/service before scale warrants them.
- **Verdict:** Compare 2 and 4 simultaneous requests as **nonbinding scenarios** only. Do not implement a pool until user demand, operation effort and resource/SLO acceptance inputs are sufficient. Do not select per-lane ext4 yet. Any candidate must prove physical backing, full-stack aggregate bounds, unique identities, restart order and fail-closed missing/replaced mounts.
- **Who ticked:** ponykiller — “tick tick tick” — on feasibility being resolved as a condition; its ext4 concern remains open pending backing-storage proof. Both authors conceded this.
- **Dissent (kept):** Local operation may become less attractive because every extra lane adds filesystem provisioning and recovery. If that work exceeds the agreed operating budget, choose a managed candidate only after its own contracts/authorization are verified.
- **Revisit trigger:** Completion of D1, agreed measurable workloads and evidence that an exact per-lane capacity model fits actual operator/storage limits.

## D4 — Keep recovery closed through unresolved Docker control work
- **Context:** An ambiguous create call might complete after a disconnect/list operation. One empty container listing or dead Docker CLI cannot exclude a late worker.
- **Options considered:** Reopen when daemon health returns; reconcile visible containers; hold global admission closed until ownership and outstanding control calls are resolved.
- **Arguments for:** cuid (Risk & Verifiability), ponykiller (Infra), gamachiel (Architect) — a late create after reopening could exceed reviewed capacity or escape the ledger.
- **Arguments against:** Longer closed admission after a daemon blip reduces availability and can make a local service appear stuck.
- **Verdict:** Any proposed concurrent design closes global admission on daemon-wide ownership uncertainty. Reopen only after exclusive controller ownership, reconciliation of every persisted creation intent and retained reservation, and evidence no outstanding control operation can later create/start an unaccounted worker. If the selected control protocol cannot prove this, remain unavailable and document operator-assisted recovery.
- **Who ticked:** None; no author disputed this boundary after Round 1.
- **Dissent (kept):** The outage cost is real. Measure and document recovery latency; do not disguise it as a harmless health retry.
- **Revisit trigger:** Real evidence or a revised lifecycle protocol proving a narrower safe recovery boundary.

## D5 — Do not infer capacity from 2/4 runs without product thresholds
- **Context:** The user wants a small-team assessment but has not defined peak demand, busy rate, acceptable time-to-first-page, growth horizon, operator effort or recurring spend.
- **Options considered:** Guess numerical readiness limits; use 2/4 tests as capacity guarantees; measure/report scenarios and leave acceptance open until the product owner selects thresholds.
- **Arguments for:** kings (Product) — report mixed preview/heavy-SQL latency, busy outcomes and starvation rather than treating throughput as fairness.
- **Arguments against:** A comparative assessment can proceed without all production SLOs.
- **Verdict:** Use mixed preview/SQL trials and report per-operation timing distributions, busy frequency, starvation and recovery latency for each scenario. Missing acceptance thresholds block production budget/readiness claims, not the assessment itself.
- **Who ticked:** kings — “tick tick tick” — withdrew the Round 1 blocker after mixed-workload criteria were added, while retaining threshold agreement as a production gate.
- **Dissent (kept):** Scenario success alone cannot establish that 2 or 4 concurrency meets team expectations or fits recurring operations cost.
- **Revisit trigger:** Product owner specifies peak/concurrency/latency/overload, dataset growth and acceptable operator/spend limits.

## D6 — Stop testing before targets and stop conditions are agreed
- **Context:** “Small team” confirms the reassessment scope, but not a production SLO or operator budget. Repeatedly tuning after sample runs would turn unknown acceptance into an open-ended implementation project.
- **Options considered:** Run provisional two/four-worker tests first and set thresholds afterward; agree a bounded workload envelope/decision rule first; stop at comparative research if the needed owner inputs are not available.
- **Arguments for:** estebanquito (Engineering Manager) — “Before experimental execution, record the workload envelope, numeric acceptance thresholds, resource/operations ceiling, and bounded experiment scope.” kings (Product) — a mixed workload and explicit time-to-first-page, busy frequency and starvation describe user impact.
- **Arguments against:** rafachafa (Pragmatist) — small two/four runs are inexpensive and useful to inform thresholds; however they do not alone establish production readiness.
- **Verdict:** Record user-approved numerical workload/SLO/cost bounds and a decision rule before executing measurements. Without these inputs, stop after comparison with “capacity undetermined.” Define each gate’s evidence applicability as preserved, invalidated, new or missing.
- **Who ticked:** rafachafa — “**tick tick tick**” — and gamachiel — “**tick tick tick — concede**.” Both agreed missing thresholds mean “capacity undetermined,” not implied budget, and new mount/concurrency probes cannot replace S3/changed-snapshot/authorized-overlap evidence.
- **Dissent (kept):** Early samples can inform later thresholds, but they are experiments only and cannot be used to claim a capacity target after the fact.
- **Revisit trigger:** The user/owner supplies enough numeric acceptance criteria to authorize a bounded measurement decision.
