# Plan: Preview a dataset by date and facility
> Status: draft · Slug: preview-facility-filter · Spec: ./spec.md

## Approach

Extend the existing preview path with one optional exact facility identifier,
carried from HTTP through application-owned sequence metadata to the isolated
worker. Reuse authorization, snapshot pins, keyset pagination and public views;
add a parameter-bound equality predicate rather than a separate filtering
abstraction. Scope is this backend repository only, including its published
contracts and consumer handoff. Web implementation and verification are excluded.
(FR1–FR5, TR1–TR3)

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
- **Verification and runtime identity records** — extend behavioral suites and
  documentation fixtures; coordinate the pinned worker image and reviewed
  runtime identity after protocol changes without activating resources in this
  planning work. (TR2, TR3, AC1–AC6)

## Data model changes

- Add an optional string facility field to the application preview request and
  in-memory sequence; absence means no facility predicate. The existing opaque
  cursor identifies that stored selection and does not accept replacements.
  (FR1, FR3)
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
  facilities/generators additionally advertise `facility`. Publish this capability
  expansion in the backend OpenAPI, fixtures and consumer handoff. A client that
  strictly expects the two-date array may reject the expanded catalog; document
  that compatibility impact without prescribing or performing client changes.
  Backend acceptance covers the API behavior, not a consumer UI. (FR5, TR3)

## Implementation phases

1. **Backend contracts and validation** — specify the optional field, identifier
   validation, per-grain capabilities and error cases in both OpenAPI copies and
   fixtures. Record catalog compatibility impact in the consumer handoff.
   (FR1, FR2, FR5, TR1, TR3)
2. **Application selection and cursor lifecycle** — carry the authorized filter
   through initial admission and immutable bounded sequence metadata. Preserve
   cursor-only continuations, expiry, ownership and snapshot behavior.
   (FR1–FR4, TR1, TR2)
3. **Isolated worker filtering** — extend strict paired transport, bind equality
   in the trusted preview query and validate returned facility identity in the
   parent. Advertise support with the complete backend implementation.
   (FR1, FR2, FR5, TR1–TR3)
4. **Backend verification and documentation** — complete acceptance coverage,
   synchronize living docs and consumer contract examples, and identify updated
   pinned worker image/protocol/runtime prerequisites. Report portable,
   PostgreSQL and actual-host evidence separately. No web work is required to
   complete these phases. (FR1–FR5, TR1–TR3, AC1–AC6)

## Dependencies & integrations

- Existing Flask/application preview service, bounded sequence store and isolated
  DuckDB worker; no additional library or external service. (TR1, TR2)
- No implementation dependency on the separate web project. Consumer handoff
  records that the existing client's strict two-date catalog decoder may require
  separate adaptation before it consumes expanded metadata. That work is outside
  this plan and does not block backend development or acceptance. (FR5, TR3)
- Worker/image digest and reviewed runtime identity must match the new strict
  protocol before use. This plan grants no service start, image activation,
  source retrieval, publication or deployment permission. (TR3)

## Risks & tradeoffs

- **Catalog consumer compatibility** — expanded capability metadata can break
  strict consumers. Document the impact in the API handoff and verify the new
  backend contract; client adaptation belongs to its own project. (FR5, TR3)
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

- Facility discovery endpoint — excluded because exact-ID filtering needs no
  existence lookup or new data-access path. (FR1, FR2, TR1)
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
- **AC5** — backend contract tests cover unchanged unfiltered/date-only preview
  requests, per-grain capability metadata, synchronized OpenAPI/fixtures and
  consumer examples. Strict paired worker protocol mismatches fail closed;
  no web tests are part of acceptance.
- **AC6** — run documented architecture, Ruff, mypy and relevant backend pytest.
  Run disposable PostgreSQL cases only with an explicit test DSN and report
  unavailable checks. Protocol/image validation and controlled tests do not
  close outstanding Linux actual-host isolation or capacity acceptance evidence.

## Assumptions

- The existing [source identifier contract](../facility-generator-verification/contract.md)
  governs exact identity; 256 UTF-8 bytes is the explicit initial application cap.
  No new architectural boundary is selected, so this product expansion requires
  synchronized living contracts rather than a superseding architectural ADR.
  (FR2, TR1)
- Unknown well-formed IDs return empty results without a facility-existence
  lookup. Client control design, implementation and verification are owned by
  the separate web project. (FR1, FR2)

## Open decisions

_None._
