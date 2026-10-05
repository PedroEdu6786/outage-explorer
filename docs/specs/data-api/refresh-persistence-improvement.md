# Refresh persistence performance improvement

Status: **proposed follow-up; no runtime change approved or implemented**.
Date: 2026-10-05.

## Problem and observed evidence

During a user-initiated live refresh, the Admin status remained `running` /
`persisting` long enough to look stalled. A read-only observation found:

- 2,788 local staging files totaling 75,282,127 bytes. This includes local
  artifacts; it is not a measured count or size of the durable graph.
- About 601 seconds since admission and 345 seconds since the last run update,
  with a healthy worker lease and 57 seconds remaining on that lease.
- The run's recorded persistence allowance was 1,800 seconds.
- A later bounded S3 metadata listing found 1,027 objects created within its
  preceding 15-minute window, totaling 26,480,076 bytes. The latest object had
  been created at 22:30:23 UTC, during observation.

These snapshots establish ongoing upload activity, not a completed refresh
duration, a transfer rate, or exact per-run progress. The listing covered the
configured shared artifact prefix; recent objects are not necessarily exclusive
to this run. No credentials, session values or cloud resource identifiers are
recorded here. The run's final outcome was not established by these checks.

## Current implementation and likely contributors

`bootstrap.build_refresh_worker` constructs one persistence worker with
`BoundedConnectorWorkers(1, ...)`. The connector CLI already supports independently
configured one-to-three S3 workers; that configuration is not exposed by the
HTTP refresh worker composition.

`PersistConnectorArtifacts.execute` verifies the local graph, transfers its
dependencies, transfers the root last, and performs fresh complete remote
readback and semantic replay before returning a durable receipt. Each
`S3ArtifactStore.put_exact` also verifies the uploaded or pre-existing object by
reading it back. Many small objects therefore incur multiple network requests,
and the broad `persisting` stage covers more than uploading bytes.

These are candidates for measurement, not a proven attribution of the live
duration. Earlier connector evidence demonstrates bounded concurrency and
source-disabled reconstruction, but cannot predict this HTTP refresh's speedup.
See [connector resource evidence](../data-connector/resource-evidence.md).

## Proposed work, in order

1. Measure local verification, dependency transfer, root transfer, remote
   readback, semantic replay and publication separately. Record completed/total
   objects, graph bytes, requests, retries, existing-object comparisons and
   monotonic durations. Keep worker diagnostics free of credentials and raw SDK
   errors. A status-visible progress extension needs an explicit HTTP contract
   update; do not invent a percentage or completion estimate.
2. Expose independently configured, bounded one-to-three persistence workers
   in the HTTP refresh worker, reusing the existing connector scheduler. Preserve
   a sequential default until representative measurements justify a change.
   Define whether configuration is frozen at admission or process startup before
   implementation. Aggregate request, byte, temporary-file and deadline budgets
   must remain shared, not multiplied by worker count.
3. Compare one, two and three workers on the same verified graph with matched
   initial S3 state. Measure new uploads, identical-object retries and recovery
   separately. Include memory, temporary disk, throttling and API/refresh overlap;
   choose configuration from measured results rather than promising a speedup.
4. Profile repeated local replay and remote verification. Investigate eliminating
   redundant internal work only where exact equality and complete verification
   can still be demonstrated. Object compaction or a changed storage graph is a
   separate design proposal, not an implicit optimization in this follow-up.

## Acceptance criteria

- Report reproducible before/after subphase and total timings, graph counts,
  bytes and resource use with matching workload and storage state. Select a
  numerical performance target after collecting a complete baseline.
- Show bounded overlap for independent transfers and equivalent verified
  contents/outcomes in sequential and concurrent modes.
- Preserve conditional immutable writes, exact checksums, root-last ordering,
  full durable readback/replay and all-three-grain atomic publication.
- Exercise corrupt/missing objects, throttling, deadlines, worker loss and stale
  ownership. Failure preserves the previous active generation; retries remain
  explicit and receipt creation alone never means publication.
- Define progress behavior through upload and readback so a healthy long-running
  stage is distinguishable from a lost worker without exposing protected data.

This proposal preserves the accepted layered monolith, independent worker,
publication fencing and storage boundaries. It authorizes no deployment,
additional live ingestion, publication, budget increase or runtime enablement.
