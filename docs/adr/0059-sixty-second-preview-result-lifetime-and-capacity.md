# ADR-0059: Use a 60-second preview/result lifetime and 100 results per user

Status: **Proposed** (records the user's direction of October 6, 2026; awaiting
user approval of this wording)

Date: 2026-10-06

## Context

[ADR-0015](0015-dataset-preview-pagination.md) accepted a fixed, unrenewed
15-minute lifetime for preview cursors, and [ADR-0020](0020-paginate-query-results.md)
applied it to retained SQL results. Neither records why 15 minutes was chosen; the
stated reasons are to bound resources and to keep a cursor on one snapshot.

During the first end-to-end test of the single-file layout, the per-user cap of 3
live preview sequences (`results_per_user`, shared with retained SQL results) was
exhausted by ordinary browsing. The fourth first-page request returned
`503 service_unavailable` for the rest of the 15-minute window, although the
analytical runtime was healthy. The user directed: 15 minutes is too long; reduce it
to seconds and raise results per user to 100. The user chose 60 seconds.

## Decision

- Preview sequences and retained SQL results expire exactly **60 seconds** after
  first-page creation or execution completion respectively, fixed and unrenewed.
  Everything else in ADR-0015 and ADR-0020 stands: 100/500 page sizes, snapshot
  binding, authorization on every page, and explicit expiry or loss errors.
- `results_per_user` becomes **100** and the global `result_count` becomes **100**
  (a user cannot exceed the global count). These are initial, unmeasured limits.
- The lifetime has one source of truth, `domain/query_results.LIFETIME_SECONDS`.
  The runtime profile validation requires both profile lifetimes to equal it.
- Total retained-result bytes, per-result reservation, output caps, page sizes and
  the single analytical execution slot are unchanged.

## Consequences

- A client must page through a result within 60 seconds. After expiry it restarts
  from the first page; a stale cursor returns `410 preview_unavailable` (previews)
  or the existing query-unavailable errors (SQL), never a silent snapshot switch.
- Pinned generations and cached public files are released sooner, so a published
  generation is retained for browsing for less time. With 100 live sequences per
  user, up to 100 pins can exist; the cache's file and byte bounds still apply.
- The retained-result byte cap (10 MiB total, with a worst-case reservation per
  in-flight result) is unchanged, so large SQL results may hit it before the count.
- `results_per_user` and `result_count` are part of the reviewed runtime profile.
  The profile identity changes, so a new local review record is required before
  the analytical API starts (ADR-0055/0056).
- ADR-0015 and ADR-0020 remain historical; only their lifetime is superseded.
  The data-api contract, OpenAPI documents and related specs are updated to 60
  seconds. Original design documents of the backend (`outage-explorer-backend/`)
  and task records are left as historical.

## References

- [ADR-0015](0015-dataset-preview-pagination.md),
  [ADR-0020](0020-paginate-query-results.md)
- [Data contract](../specs/data-api/http-contract.md)
