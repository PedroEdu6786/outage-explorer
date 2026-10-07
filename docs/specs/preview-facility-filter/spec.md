# Spec: Preview a dataset by date and facility
> Status: implemented; portable backend acceptance verified; runtime gaps recorded · Slug: preview-facility-filter

## Problem and approved scope

The challenge story asks: “As an Analyst, I want to preview a dataset filtered
by date and facility.” Earlier preview supported dates only; SQL filtering did
not fulfill this story. The user requested this addition and selected
**one facility at a time**, applied to facility and generator datasets.
This specification covers this backend repository only. Web implementation,
UI design and web verification belong to the separate project and are excluded.
This extends the initial date-only decision recorded in the
[data API contract](../data-api/http-contract.md); it changes product filter scope,
not the accepted architecture or role model. Existing unfiltered/date-only
behavior remains supported. No historical ADR is rewritten.

## Requirements

- **FR1:** Analyst/Admin can start `facilities` or `generators` preview with an
  optional single exact facility identifier, combined with optional inclusive
  `start_date`/`end_date`. Every returned row must satisfy all supplied filters.
  Omission means all authorized facilities; facility names, lists, wildcards,
  substring search and generator-specific filtering are excluded.
- **FR2:** Treat facility as a string identifier, preserving leading zeros and
  exact identity. A valid identifier with no matching observations returns a
  normal empty preview without a separate facility-existence lookup. Reject
  empty/malformed/oversized identifiers and repeated parameters explicitly;
  reject facility filtering for `national` rather than ignoring it. Match the
  source identifier contract and document a finite UTF-8 byte bound.
- **FR3:** Bind the selected facility, dates, page size, owner and generation to
  the initial preview sequence. Continuations accept only `cursor`; filter
  changes start a new sequence. Preserve deterministic keyset ordering, page
  revisits, refresh snapshot isolation, fixed 60-second expiry and cleanup.
- **FR4:** Preserve current application-owned authorization on every page.
  Viewer cannot access facility or generator data, including through filtered
  requests, cursor reuse or direct use-case calls. Unauthorized requests must
  reach neither analytical preparation nor execution.
- **FR5:** Catalog `supported_filters` advertises facility only for `facilities`
  and `generators`. Synchronize the HTTP contract, both OpenAPI copies, fixtures,
  UI handoff and relevant living requirements when implementation lands.

## Technical constraints

- **TR1:** Extend existing layer-first preview service/ports and isolated worker
  request; apply parameter-bound equality in the worker's trusted preview query.
  No user SQL construction in routes, new filtering framework, persistence stack,
  source fetch, Parquet rebuild, facility discovery endpoint or schema migration.
- **TR2:** Preserve three unified resources and public-only views, bounded staging,
  worker isolation, one analytical slot, response/page limits and pin/reaping
  safeguards. Charge facility bytes to sequence metadata and bound/validate the
  field on both application and worker boundaries. Existing requests without the
  facility parameter retain their preview behavior; catalog capability changes
  are documented separately.
- **TR3:** Coordinate the paired backend worker/image/protocol identity and
  document the API compatibility impact for consumers. Expanded catalog filter
  metadata can affect strict client decoders; record that impact in this
  repository's handoff without adding web changes or tests to this plan.
  Backend implementation and acceptance do not depend on web work. Planning
  authorizes no service start, image activation, publication or deployment.

## Acceptance criteria

- [x] **AC1 (FR1–FR2):** Known multi-facility fixtures prove facility-only,
  combined inclusive-date/facility, leading-zero exact-match and empty-result
  behavior for both supported grains; unfiltered/date-only results remain unchanged.
- [x] **AC2 (FR2, FR5):** HTTP/application/worker validation covers unsupported
  national filtering, empty/invalid/oversized/duplicate values and malicious input;
  SQL treats supplied IDs as bound values. Catalog/OpenAPI/fixtures agree by grain.
- [x] **AC3 (FR3, TR2):** Multiple filtered pages concatenate to the expected
  ordered rows without skips/duplicates; revisits agree, new publication cannot
  change the original sequence, cursor-plus-filter is rejected, and expiry/store
  loss and active-reader cleanup preserve existing behavior and resource bounds.
- [x] **AC4 (FR4):** Viewer/unauthenticated/expired/revoked access is denied before
  preparation/execution; foreign cursors and role changes cannot reveal detail.
- [x] **AC5 (FR5, TR3):** Backend contract tests prove unchanged unfiltered/date-only
  preview behavior and correct per-grain supported-filter metadata. OpenAPI,
  fixtures and consumer handoff describe the new parameter and catalog impact.
  Paired backend/worker protocol mismatch remains fail-closed.
- [x] **AC6 (TR1–TR3):** Backend architecture/Ruff/mypy and relevant pytest suites
  pass. Distinguish portable tests, disposable PostgreSQL checks and actual-host
  runtime checks; report unavailable checks explicitly without claiming
  live/production acceptance. Web tests and end-to-end UI acceptance are excluded.

Acceptance is for the approved portable backend scope. See
[verification.md](verification.md) for exact evidence, unrun disposable PostgreSQL
and actual-host checks, image/profile prerequisites and remaining runtime gaps.
These checkboxes do not certify deployed behavior, isolation or web acceptance.

## Open clarifications

None blocking. The plan selects the identifier bound from current contracts and
covers backend/worker compatibility. A separate web-project plan may consume the
published API contract; its design and delivery are outside this scope.
