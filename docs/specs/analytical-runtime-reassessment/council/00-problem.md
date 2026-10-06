# Small-team analytical runtime — Problem Anchor

## The Main Problem
Keep user SQL isolated and responsive as a small team's dataset and concurrent usage grow, without excessive preparation overhead or operational complexity. Determine whether to simplify the current execution design or change runtime/service before increasing limits.

## Context
- User requested a step back from repeated limit fixes, explicitly asking why Docker was selected and whether alternatives fit better. User confirmed **a small concurrent team** as the evaluation target.
- At `cf81327`, the genuine 549-file workload was rejected before Docker creation: 141,646 mount-argument bytes exceeded the controller's 131,072-byte request allowance; worker JSON was 58,458 bytes. Total public input was 2,199,347 bytes. This is an application admission failure, not evidence of Docker saturation.
- `inputs.py` already copies verified approved files into a fresh execution-private directory; `docker.py` adds one bind per staged file. File-count overhead and data volume are distinct.
- `VerifiedLauncher` holds one execution lock; the finite ext4 quota adapter holds one filesystem lock and rejects another execution directory. The mutable runtime lifecycle and recovery ledger also require deliberate concurrent ownership.
- ADR-0007/0008/0012/0013 require bounded isolated DuckDB, authorized cached Parquet and defined query semantics. Docker became the chosen mechanism in the analytical-runtime follow-up; those earlier ADRs do not require Docker specifically.
- Current matching evidence includes 19 real synthetic isolation/lifecycle probes. Representative execution, Linux API/refresh overlap and correlated S3 transfer evidence remain incomplete.

## Known constraints
- Planning only; no changed runtime, cloud actions, refresh, publication or enablement.
- Preserve existing completed phases, evidence and append-only history.
- Single product/API owner, role-only authorization, snapshot-bound preview, exact retained-result paging, no SQL in API process.
- Existing one-query rule is accepted in ADR-0013. The new concurrency goal is an evaluation request; a changed production rule needs an accepted replacement decision.
- Ten-second execution ceiling is distinct from preparation, overall request time and any proposed queue wait.
- Team peak demand, latency/busy targets, growth horizon, operational ownership and budget are unknown. The comparison uses 2 and 4 simultaneous requests as experimental scenarios only.

## Out of scope (declared up front)
- Code, detailed implementation task breakdown, provisioning, migration and activation.
- Treating public candidate projection verification as complete provenance replay or publication proof.
- Treating vendor claims or synthetic stress fixtures as measured product capacity.

## Council seated
| Persona | Seat | Why seated |
|---|---|---|
| rafachafa | Pragmatist Senior Dev | Simplicity and proportionality |
| gamachiel | Architect | Growth, contracts and alternatives |
| estebanquito | Engineering Manager | Delivery sequence and acceptance |
| kings | Product | Small-team responsiveness and behavior |
| ponykiller | Infra / SRE | Aggregate capacity, quotas and operation |
| cuid | Risk & Verifiability | Untrusted SQL and concurrent isolation |

## Mode & sizing
Greenfield **reassessment documents**, preserving the existing runtime specification and completed phases. Two blind proposals, up to two focused debate rounds, six seats, target approximately 16 agent turns. This is a proposed evaluation plan, not a reopened implementation phase or accepted migration.

## Interrogation outcome
- All six reviewers distinguished the observed metadata-cap failure from compute saturation.
- All six requested a concrete concurrency/latency target; four also stressed dialect/result/operational tradeoffs in managed execution. The already confirmed small-team direction is sufficient to compare designs; unknown numeric targets remain explicit in the spec.
- `cuid` and `ponykiller` identified whole-filesystem spill ownership as a blocker to merely increasing a semaphore.
- `kings` and `estebanquito` required separate preview/SQL latency, overload outcomes and an explicit distinction between evaluation and production readiness.

## Primary-source reconnaissance
Consulted October 5, 2026; documentation is capability evidence, not a benchmark of this application.
- [DuckDB security guidance](https://duckdb.org/docs/current/operations_manual/securing_duckdb/overview): untrusted SQL requires additional sandboxing; engine configuration alone is insufficient.
- [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/): files or directories can be bound read-only; recursive submount inclusion must be handled explicitly.
- [DuckDB file-format guidance](https://duckdb.org/docs/current/guides/performance/file_formats): file/row-group layout affects query performance; published examples are not measurements for the pinned product version.
- [Athena overview](https://docs.aws.amazon.com/athena/latest/ug/what-is.html), [SQL](https://docs.aws.amazon.com/athena/latest/ug/using-athena-sql.html), [quotas](https://docs.aws.amazon.com/athena/latest/ug/service-limits.html): managed S3 query execution brings another SQL contract and queued execution/admission.
- [Fargate architecture](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html): managed container tasks have separate isolation boundaries; the application still owns data transfer, authorization and result orchestration.
- [MotherDuck compute model](https://motherduck.com/product/hypertenancy/): vendor documents DuckDB instances per account and read scaling; compatibility, cancellation, resource/spend bounds and latency need product-specific evaluation. Its documentation endpoint was inaccessible through the research tool; no unavailable documentation was treated as verified.
- [NsJail project](https://github.com/google/nsjail): another Linux namespace/cgroup/seccomp isolation mechanism; replacing Docker does not remove application resource/ownership obligations.
