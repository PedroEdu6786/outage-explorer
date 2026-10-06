# Small-team analytical runtime — Risks & Test Scenarios

## Edge cases
- **EC1:** 549 verified files need more Docker argument bytes than the bounded launcher allows → reject before daemon work with a safe resource error; a separate measurement must establish mount metadata and file-count scale (FR6).
- **EC2:** Two files share one digest but descriptors conflict or a file changes while preparing → reject the request and expose no altered data (FR2).
- **EC3:** A directory mount includes an unexpected file, symlink, device or nested mount → refuse admission or prove the worker cannot read it (FR2).
- **EC4:** Source directory is replaced/renamed or modified between validation and Docker resolving its bind → preserve inode identity and no-write ownership or fail closed (FR2, FR4).
- **EC5:** Two workers run at once, one exceeds spill/inodes while the other reads a different snapshot → enforce independent request ceilings and preserve other result/data (FR1–FR3).
- **EC6:** Simultaneous cold preparation uses host CPU/memory/disk while refresh is active → preserve measured API/refresh headroom or return bounded busy (FR1, FR5).
- **EC7:** Busy response repeats for preview requests while expensive SQL fills all slots → measure per-operation busy rate/starvation; no unapproved priority/queue assumption (FR1, FR5).
- **EC8:** Timed-out Docker create later starts after daemon reconnection → global admission stays closed until persisted intent and all potential control operations are reconciled (FR4, FR5).
- **EC9:** A lane filesystem is a sparse file on an undersized shared host disk, or mount vanishes at reboot → do not treat filesystem logical capacity as reserved physical capacity; fail closed on backing/mount identity (FR1, FR4–FR5).
- **EC10:** Managed query completes after caller timeout, returns changed numeric types, or reads a moved snapshot → preserve/cancel exact execution or explicitly revise contracts before choosing provider (FR3–FR4).

## Failure modes
- **FM1:** Argument bound is raised solely to force this sample through → path count remains proportional to partitions and other requests still serialize; require independent argument/manifest bounds and one-directory measurement (FR6).
- **FM2:** Semaphore count rises without aggregate admission → concurrent preparation, encoding, spill and controller processes exhaust host resources; reserve all phases and close admission when resources/ownership cannot be proven (FR1, FR5).
- **FM3:** Read-only bind is called “immutable” while host mutates or reuses path → worker observes unverified inputs; protect exact directory identity/lifetime and test races (FR2).
- **FM4:** Recovery checks daemon health only → late create escapes reviewed ownership; reconcile delayed-create operations before reopen (FR4–FR5).
- **FM5:** Per-lane ext4 uses sparse backing without aggregate disk accounting → several individually valid filesystems exhaust shared storage; measure real physical backing and all host consumers (FR1, FR5).
- **FM6:** Athena/MotherDuck/Fargate is called a drop-in → authorization, SQL, cancellation, results, snapshot or billing changes silently; complete compatibility matrix and authorized test first (FR3, FR6).

## Key test scenarios
- **TS1 (AC1):** Trace representative national/facility/generator queries and preview through Docker, Athena, MotherDuck, Fargate and NsJail options; report SQL/types/auth/snapshot/result/deadline differences as verified, unknown or incompatible.
- **TS2 (AC2, AC6):** With independently authorized refresh/API overlap and real unchanged/changed snapshot identities, run 1/2/4 workers using preview-only, heavy SQL and mixed arrival patterns. Report preparation/execution/time-to-first-page distributions, successful/busy counts, fairness/starvation, API/refresh latency, CPU/memory, staging/cache/spill/result physical bytes, transfer and sample coverage. 2/4 are experiments, not pass targets.
- **TS3 (AC3):** Mutate, replace, add, delete, symlink and nest mounts around directory finalization/launch; run simultaneous workers with different authorized input sets and attempt cross-read/write. Verify exact manifest/digest-to-directory identity and no host mutation.
- **TS4 (AC4):** Concurrent requests against old/current snapshots with repeated/revisited pages, user-role revocation, duplicate rows and failures; concatenate each query's pages and verify exact original retained result without a second execution.
- **TS5 (AC5):** Stall/reorder create/start, lose CLI/daemon connectivity, delay control completion until after reconnect, kill workers with children and restart supervisor. Confirm no reopening while an unaccounted worker may start; per-lane uncertainty retains all reservations; prove explicit operator recovery path if reconciliation cannot be established.
- **TS6 (AC2, AC5):** Exhaust each lane's bytes/inodes and physical backing; restart with missing/replaced mounts, shared device aliases and undersized backing; ensure remaining application/refresh storage and API headroom survive.
- **TS7 (AC1, AC6):** For each managed alternative, document query language/type corpus, role enforcement, who can fetch result objects, snapshot binding, sync/async timing, timeout cancellation, per-query billing/quotas, retention, data movement and operator tasks. Mark untested claims as unknown.

## Accepted risks
- The immediate failure has no real worker/query memory sample; DuckDB/container memory sufficiency remains unknown.
- Current old/current candidates have identical public hashes, so their comparison does not evidence a changed-generation cache miss or refreshed contents.
- Any 2/4 scenario result is only a measured workload point; future demand and acceptance thresholds remain open.
- Primary vendor documentation, even where it advertises managed compute/security/scaling, does not validate the project-specific contract or operating cost.
- Global admission closure during uncertain daemon ownership may reduce availability; the competing risk is an unaccounted live worker and unsafe capacity reuse.

## Directory-mount implementation status — 2026-10-05

The request-private staging directory now contains only verified digest-named
Parquet files, is sealed mode `0555` after final exact-entry verification, and
is passed to Docker as one read-only `bind-recursive=disabled` mount at
`/inputs`. Individual Parquet files remain mode `0444`. Cleanup restores
directory-owner write permission only after the existing caller lifecycle has
confirmed worker termination.

Controlled verification passed 41 tests across
`tests/integration/test_analytical_input_staging.py` and
`tests/unit/test_docker_runtime.py`; Ruff check/format, mypy on the changed
adapters, and `git diff --check` passed. Pytest emitted four temporary-directory
cleanup warnings in `test_dedicated_pool_private_mode`; the selected tests passed.
These controlled checks do not prove Docker mount behavior or worker isolation.

The owner authorized code and isolation/lifecycle tests while keeping latency
and resource targets open, and explicitly excluded performance/capacity
measurements. Native Linux Docker isolation has not run. The documented guest
export uses `git archive HEAD` only after committing the reviewed implementation
and explicitly refuses a stale source export; the implementation is currently
uncommitted. Do not bypass that guard. T3.2/T3.C remain open pending the
documented guest validation; no performance, capacity, API/refresh-overlap or
throughput measurements are authorized.
