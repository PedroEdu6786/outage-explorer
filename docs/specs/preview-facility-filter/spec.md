# Spec: Preview a dataset by date and facility
> Status: planned, not implemented · Slug: preview-facility-filter

## Problem and approved scope

The challenge story asks: “As an Analyst, I want to preview a dataset filtered
by date and facility.” Current preview supports dates only; SQL filtering does
not fulfill this story. The user requested planning this addition and selected
**one facility at a time**, applied to facility and generator datasets.
This extends the initial date-only decision recorded in the
[data API contract](../data-api/http-contract.md); it changes product filter scope,
not the accepted architecture or role model. Existing date-only behavior remains
implemented until this feature ships. No historical ADR is rewritten.

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
- **FR6:** The separate web client exposes a facility-ID input for supported
  datasets alongside dates, submits it on initial previews, retains it on cursor
  pages and restarts browsing on changes. Empty UI input omits the filter; national
  preview hides/clears it. Show existing empty/error/expiry states correctly.

## Technical constraints

- **TR1:** Extend existing layer-first preview service/ports and isolated worker
  request; apply parameter-bound equality in the worker's trusted preview query.
  No user SQL construction in routes, new filtering framework, persistence stack,
  source fetch, Parquet rebuild, facility discovery endpoint or schema migration.
- **TR2:** Preserve three unified resources and public-only views, bounded staging,
  worker isolation, one analytical slot, response/page limits and pin/reaping
  safeguards. Charge facility bytes to sequence metadata and bound/validate the
  field on both application and worker boundaries. Existing unfiltered clients
  must continue to work against the updated backend.
- **TR3:** Coordinate backend worker/image/protocol identity and web compatibility.
  The current web decoder requires exactly the two date filters; it must accept
  the new supported-filter capability before backend catalog output changes.
  Planning authorizes no service start, image activation, publication or deployment.

## Acceptance criteria

- [ ] **AC1 (FR1–FR2):** Known multi-facility fixtures prove facility-only,
  combined inclusive-date/facility, leading-zero exact-match and empty-result
  behavior for both supported grains; unfiltered/date-only results remain unchanged.
- [ ] **AC2 (FR2, FR5):** HTTP/application/worker validation covers unsupported
  national filtering, empty/invalid/oversized/duplicate values and malicious input;
  SQL treats supplied IDs as bound values. Catalog/OpenAPI/fixtures agree by grain.
- [ ] **AC3 (FR3, TR2):** Multiple filtered pages concatenate to the expected
  ordered rows without skips/duplicates; revisits agree, new publication cannot
  change the original sequence, cursor-plus-filter is rejected, and expiry/store
  loss and active-reader cleanup preserve existing behavior and resource bounds.
- [ ] **AC4 (FR4):** Viewer/unauthenticated/expired/revoked access is denied before
  preparation/execution; foreign cursors and role changes cannot reveal detail.
- [ ] **AC5 (FR6, TR3):** Web tests prove capability-driven input, correctly encoded
  initial request, cursor-only continuation, changed-filter restart, dataset-switch
  clearing and empty/error/expiry handling. Test the old date-only catalog and
  updated catalog, including real adapter mapping rather than fixture UI alone.
- [ ] **AC6 (TR1–TR3):** Backend architecture/Ruff/mypy and relevant pytest suites
  pass; web documented lint/type/test/build checks pass. Distinguish portable tests,
  disposable PostgreSQL checks and actual-host runtime checks; report unavailable
  checks explicitly without claiming live/production acceptance.

## Open clarifications

None blocking. Recommended initial UI is a labeled facility-ID text field;
complete dropdown discovery would need separate scope and bounded data sourcing.
The plan must select the identifier bound from current contracts and describe
worker/client compatibility without introducing an unnecessary abstraction.
