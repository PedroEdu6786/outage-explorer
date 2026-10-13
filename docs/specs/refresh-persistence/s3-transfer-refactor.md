# S3 resource transfer refactor plan

Status: **Implemented with focused verification** (October 13, 2026). This reorganizes the adapter without changing the
accepted persistence contract in ADR-0060 and ADR-0061.

## Problem found in the current code

`S3ArtifactStore` in `infrastructure/s3/artifacts.py` implements the former
`objects/<sha256>` layout, metadata discovery through `HEAD`, conditional PUT,
verified GET, retries, and shared transfer accounting in one class.
`S3ResourceStore` inherits it but replaces `_key()` to use generation-scoped
resource addresses and disables `reference()` because recovery now receives exact
descriptors. Product composition constructs `S3ResourceStore`; direct
`S3ArtifactStore` construction remains in tests. The inheritance makes the
current resource adapter depend on a superseded storage contract and hides
which validation and accounting steps each operation performs.

## Target shape

- Keep one public concrete adapter, `S3ResourceStore`, implementing the existing
  application-owned `ResourceTransfers` port. It coordinates address validation,
  aggregate admission, transfer, and recovery staging. Preserve constructor
  inputs used by bootstrap and the refresh pipeline.
- Place the three filenames, generation-scoped address mapping, and receipt
  validation in the concrete `ResourceAddresses` class. Keep conditional PUT,
  retry/error handling, and streamed SHA-256 readback in the concrete
  `ResourceObjectTransfer` class. These are internal infrastructure collaborators,
  not new application ports or stores.
- Give aggregate accounting a small private component in
  `infrastructure/s3/transfer_budget.py`. It owns the lock, cancellation/deadline,
  request count, wire bytes, temporary staging reservation, and admitted object
  descriptors. Every concurrent transfer shares this one instance. Reject a
  second descriptor for the same physical key if its checksum or size differs.
- Keep SDK calls and their retry/error translation in
  `resource_object_transfer.py`, organized into named steps for upload staging,
  conditional PUT, GET admission, and streamed verification. Do not add an
  abstract base class, generic object
  store, or caller-selected S3 key/URL interface.
- Remove `S3ArtifactStore` and its `objects/<sha256>`/`HEAD` path once current
  resource behavior is covered directly. Remove the unused `ArtifactStore` and
  `ExactArtifactStore` ports if the final reference search still finds no callers.
  Keep `StoredObject`, bounds and error types used by the resource port.

## Behavior to preserve

1. Exactly the three ADR-0061 addresses under
   `<prefix>generations/<generation-id>/`; local checksum identity remains
   distinct from the physical S3 key. Recovery accepts supplied exact
   descriptors and never discovers objects with `HEAD`, listing, or a manifest.
2. Each write validates local byte count and SHA-256 before its first SDK call;
   uses a single conditional `PutObject` with `IfNoneMatch="*"` and
   `ChecksumSHA256`; and succeeds only after full GET readback verifies count
   and digest. An existing identical object may be reused; conflicting bytes
   fail without overwrite or deletion.
3. Retries, deadline, cancellation, requests, wire bytes, object totals and
   staging reservations stay aggregate across the one to three workers. A
   failed/late operation cannot produce a durable receipt. Recovery staging
   remains reserved until worker join and local verification finish.
4. GET bodies close on success, corruption, interruption, early generator
   close, and deadline expiry. SDK details and secret-bearing errors never
   appear in public errors or logs. Preserve useful attempt/skip/failure logs.

## Sequence

1. **Move the evidence to the current contract.** Rework controlled S3 tests
   to construct `S3ResourceStore` with generation-scoped descriptors. Retain
   cases for conditional parameters, retries, uncertain PUT completion,
   identical/conflicting existing objects, corruption, close behavior,
   cancellation, aggregate limits and parallel workers. Replace the obsolete
   metadata-discovery test with a receipt-validation case. Keep the real SDK
   `Stubber` check and the controlled fake; do not require live AWS.
2. **Extract shared accounting.** Move only the lock-protected state and budget
   operations into the private transfer budget. Verify the same budget instance
   is used by uploads, readbacks and recovery staging. Avoid changing error
   ordering or charging semantics during this step.
3. **Make the resource adapter direct.** Replace inherited `_key()`/`put_exact()`
   behavior with `ResourceAddresses` and `ResourceObjectTransfer`, coordinated
   by `S3ResourceStore` and the shared budget. Keep the `ResourceTransfers`
   public methods and bootstrap wiring stable.
4. **Remove the legacy surface.** Delete `artifacts.py` after all imports are
   gone, retire unused ports, and update the S3 structure notes. Do not edit
   historical ADRs, prior specification evidence, or devlog entries.

## Completion checks

- Source and tests contain no product dependency on `S3ArtifactStore`,
  `objects/<sha256>`, or `head_object` for resource persistence/recovery.
- Focused controlled S3, concurrency, resource-persistence, recovery and refresh
  failure cases pass, including no receipt/publication after failed readback.
- Ruff, mypy, architecture checks and `git diff --check` pass. Compare the
  public `ResourceTransfers` signatures and constructor wiring before/after.
- The current instruction pauses unit tests. Focused controlled S3 integration
  checks are allowed; implementation reports any broader checks deferred by
  that pause instead of claiming a full behavior gate passed.

## Implementation result

`S3ResourceStore` owns the resource contract directly and delegates to
`ResourceAddresses`, `ResourceObjectTransfer`, and the shared `TransferBudget`.
The legacy artifact store and its unused ports are removed. After the class
split, 61 controlled S3, concurrency and resource persistence cases passed;
two targeted checks passed for early stream closure and exact descriptor bounds.
Ruff, mypy and the architecture rule scan passed. Unit tests remain paused.
