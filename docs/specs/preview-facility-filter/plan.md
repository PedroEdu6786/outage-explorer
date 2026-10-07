# Plan: Preview a dataset by date and facility
> Status: draft · Slug: preview-facility-filter · Spec: ./spec.md

## Approach

Extend the existing preview path with one optional exact facility identifier,
carried from HTTP through application-owned sequence metadata to the isolated
worker. Reuse authorization, snapshot pins, keyset pagination and public views;
add a parameter-bound equality predicate rather than a separate filtering
abstraction. Implement the corresponding capability and input in the separate
web client, with client compatibility preceding expanded catalog output.
(FR1–FR6, TR1–TR3)

## Components affected

- **HTTP schemas and published contracts** — accept the optional initial-request
  field, reject duplicates and cursor/filter mixtures, and synchronize both
  OpenAPI copies, fixtures, HTTP contract, UI handoff and living requirements.
  Correct the stale manifest references in the preview flow documentation when
  documenting the actual three-resource flow. (FR2, FR3, FR5, TR1)
- **Preview application service and ports** — validate the identifier after
  existing authorization and before analytical preparation; extend `PreviewRead`,
  `PreviewSequence` and sequence creation with the selected facility. Preserve
  direct-use-case enforcement and reauthorization on every page. (FR1–FR4, TR1)
- **Bounded preview sequence store** — retain facility with the immutable sequence
  selection and include its UTF-8 bytes in metadata capacity accounting, without
  changing cursor ownership, expiry, active-reader or reaping semantics.
  (FR3, TR2)
- **Worker transport and trusted preview execution** — extend request encoding
  and strict decoding, validate the field independently, bind it to equality on
  the public `facility` column, and reject returned rows whose facility differs
  from the approved selection in the parent response decoder. (FR1, FR2, TR1–TR3)
- **Catalog service** — advertise the additional capability by grain, with the
  current authorization-based dataset visibility unchanged. (FR4, FR5)
- **Separate web client** — extend catalog validation/mapping, filter contracts,
  preview adapter/service validation, explorer controls and browsing state.
  Existing `facilityId` selection support is a starting point; current adapter
  rejection and date-only `PreviewFilters` presentation must also change.
  (FR6, TR3)
- **Verification and runtime identity records** — extend behavioral suites and
  documentation fixtures; coordinate the pinned worker image and reviewed
  runtime identity after protocol changes without activating resources in this
  planning work. (TR2, TR3, AC1–AC6)

## Data model changes

- Add an optional string facility field to the application preview request and
  in-memory sequence; absence means no facility predicate. The existing opaque
  cursor identifies that stored selection and does not accept replacements.
  (FR1, FR3)
- Add an explicit web facility-filter capability boolean, separate from any
  existing facility option list. An empty option list must not imply filtering
  is unsupported. The text field needs no discovery data. (FR5, FR6)
- No PostgreSQL migration, Parquet schema change, durable query metadata or
  publication changes. Three unified resources and public views remain intact.
  (TR1, TR2)

## Interfaces & contracts

- **Initial preview HTTP:** optional `facility` query string on
  `/api/datasets/{dataset}/preview`, valid only for `facilities` and `generators`.
  It combines with existing inclusive date bounds and page size. Absence retains
  existing behavior; a valid unmatched identifier returns the normal empty
  envelope. Continuation accepts only `cursor`; existing error/status shapes
  remain in use, with invalid filter input returning `400 invalid_request`.
  (FR1–FR3)
- **Identifier validation:** opaque string of 1–256 UTF-8 bytes; preserve case,
  leading zeros and alphanumeric identity. Reject surrounding whitespace,
  Unicode control characters, malformed Unicode/UTF-8, non-string values and
  repeated HTTP parameters; never trim, numerically coerce or normalize identity.
  The 256-byte ceiling is a chosen application resource bound, not a measured
  EIA limit. Share the pure validation rule between application and worker
  boundaries without importing transport or infrastructure into application.
  (FR2, TR1, TR2)
- **Application/worker:** optional facility in `PreviewRead` and sequence creation;
  worker JSON carries an explicit nullable `facility`. Extend the exact accepted
  field set and protocol version for the paired API/worker release; reject
  mismatches instead of adding an old-worker fallback. Worker execution binds
  the identifier as a value, using trusted dataset metadata for column names.
  Preserve period descending and binary identifier ascending keyset order.
  Parent response validation checks facility equality alongside existing date,
  column, row/key and ordering checks. (FR1–FR3, TR1–TR3)
- **Catalog:** national `supported_filters` remains `start_date`, `end_date`;
  facilities/generators additionally advertise `facility`. Web accepts both the
  old two-date catalog and the expanded per-grain catalog, maps the capability
  explicitly, and encodes the selected ID with the existing URL parameter API.
  Empty UI input omits the parameter; whitespace-only input is invalid rather
  than silently normalized. (FR2, FR5, FR6, TR3)
- **Web browsing:** retain selection in page state while continuation transport
  sends only the cursor. Applying a changed facility or dates starts a new
  sequence; switching to national clears/hides facility. Existing empty,
  validation, expiry and unavailable states remain visible. (FR3, FR6)

## Implementation phases

1. **Compatible contracts and client capability foundation** — synchronize the
   proposed wire contracts and prepare the web decoder/mapping to accept both
   catalog shapes while keeping controls capability-driven. An old date-only
   backend still works; this client compatibility must precede expanded catalog
   output. (FR5, FR6, TR3)
2. **Bounded backend selection and execution** — carry validated facility through
   initial admission, sequence storage, strict worker transport, bound query and
   response validation; advertise support only with the complete paired backend
   implementation. Existing unfiltered paths retain their behavior and controls.
   (FR1–FR5, TR1, TR2)
3. **Web browsing integration** — wire the facility-ID text field, initial request,
   cursor navigation and restart/dataset-switch behavior through the real adapter
   and application service. No facility discovery endpoint is needed. (FR3, FR6)
4. **Behavioral verification and release compatibility** — complete acceptance
   coverage, synchronize living documentation and identify the updated pinned
   worker image/protocol/runtime review prerequisites. Report portable,
   PostgreSQL and actual-host evidence separately; deployment or activation
   requires its own authorization. (TR1–TR3, AC1–AC6)

## Dependencies & integrations

- Existing Flask/application preview service, bounded sequence store and isolated
  DuckDB worker; no additional library or external service. (TR1, TR2)
- Coordinated changes in `outage-explorer-web`, whose current catalog Zod schema
  requires exactly two date filters and whose adapter rejects `facilityId`.
  Planning here describes that client work; implementation must have write
  authorization in that separate workspace. (FR6, TR3)
- Worker/image digest and reviewed runtime identity must match the new strict
  protocol before use. This plan grants no service start, image activation,
  source retrieval, publication or deployment permission. (TR3)

## Risks & tradeoffs

- **Web catalog compatibility** — prepare the tolerant client decoder first;
  retain per-grain capability validation and test both catalog shapes. (FR5, TR3)
- **API/worker mismatch** — release the strict protocol change with its pinned
  image and refresh the applicable review identity; reject mismatches with no
  weaker execution fallback. (TR3)
- **Identity drift or injection** — keep opaque strings unchanged, bind values,
  validate bounded UTF-8 at both boundaries and verify returned row identity.
  Reject controls; do not invent a numeric-only EIA contract. (FR1, FR2, TR1)
- **Sequence/resource regressions** — store the immutable filter, charge its
  bytes and exercise expiry, active readers, reaping and publication changes.
  A narrow equality predicate does not justify relaxing existing limits or
  claiming measured performance. (FR3, TR2)

### Alternatives considered

- Facility dropdown/discovery — rejected for this scope because a complete,
  bounded option source would require additional product and API design. (FR6)
- Filtering only in the client or after worker pagination — rejected because
  it produces incomplete pages and incorrect continuation/empty behavior. (FR1, FR3)

## Test strategy

- **AC1** — portable multi-facility Parquet/worker fixtures cover both grains,
  facility-only and combined inclusive dates, leading zeros and alphanumeric
  exact identity, case distinctions, unmatched IDs, and unchanged unfiltered
  results. Include IDs containing quotes to demonstrate bound-value handling.
- **AC2** — HTTP, direct-service and raw worker protocol tests cover national,
  duplicates, empty/whitespace/control/malformed Unicode, byte-bound edges,
  oversized and non-string inputs. Verify catalog by role/grain, both OpenAPI
  copies and generated/example fixtures; reject hostile returned rows from a
  fake worker at the parent boundary.
- **AC3** — service/store/worker integration compares concatenated filtered
  pages with expected sorted fixture rows, revisits and snapshot pinning across
  publication changes. Test cursor-plus-facility rejection, fixed 60-second
  expiry/store loss, metadata exhaustion including facility bytes and retained
  active-reader/reaping ownership without repeating live service activation.
- **AC4** — direct use-case and HTTP denial-before-preparation/execution tests
  cover Viewer, absent/expired/revoked sessions, foreign cursors and changed
  roles. Use explicit call observation so a denial cannot pass after data access.
- **AC5** — web adapter/service/component tests cover old/new catalogs, capability
  mapping, encoded initial facility, cursor-only continuation, selection changes,
  national switching, empty/error/expiry states and absence of discovery calls.
- **AC6** — run documented architecture, Ruff, mypy and relevant backend pytest;
  run web documented lint/type/test/build checks in its workspace. Run disposable
  PostgreSQL cases only with an explicit test DSN and report unavailable checks.
  Protocol/image validation and controlled tests do not close outstanding Linux
  actual-host isolation or capacity acceptance evidence.

## Assumptions

- The existing [source identifier contract](../facility-generator-verification/contract.md)
  governs exact identity; 256 UTF-8 bytes is the explicit initial application cap.
  No new architectural boundary is selected, so this product expansion requires
  synchronized living contracts rather than a superseding architectural ADR.
  (FR2, TR1)
- The initial UI is a labeled facility-ID text input. Unknown well-formed IDs
  remain valid empty queries rather than requiring a facility-existence lookup.
  (FR1, FR2, FR6)

## Open decisions

_None._
