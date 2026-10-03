# Plan: Trustworthy national outage data and daily offline share
> Status: draft · Slug: national-data-verification · Spec: ./spec.md

## Approach

Add an offline verification use case to the accepted layered monolith, with pure
national-data policies, injected recorded-evidence access, and a contributor CLI.
Replay the fixed September 2026 source snapshot into a versioned verification
report containing selected observations, exact calculations, exclusions, coverage
and provenance; retain the source bytes separately. This implements the focused
spec without live ingestion, product endpoints or publication infrastructure.
The health scaffold remains the existing application foundation. (FR1–FR16, TR1–TR4)

## Components affected

- **Domain national contracts and policies** — validate observations, resolve
  daily duplicates/conflicts, calculate exact shares and apply presentation
  rounding; follow ADR-0027/0031/0034/0035. (FR1–FR2, FR4–FR12, FR15, TR2–TR4)
- **Application evidence service, DTOs and ports** — coordinate evidence loading,
  validation, selection, coverage and report production without framework or I/O
  dependencies. (FR3, FR6, FR13–FR16, TR1)
- **Infrastructure recorded-evidence and report adapters** — load local JSON,
  verify manifest checksums, preserve source ordering, and serialize deterministic
  JSON plus a readable Markdown report. These are verification artifacts, not
  replacements for future S3/Parquet or operational PostgreSQL. (FR3, FR11–FR14, TR1–TR3)
- **CLI entry point and bootstrap composition** — explicitly construct the
  offline service and invoke it; extend the architecture checker's narrow startup
  coverage for CLI composition and reviewed standard-library imports, preserving
  negative fixtures and the existing HTTP exception. (FR13–FR16, TR1)
- **Versioned national evidence bundle and contract documentation** — retain
  the baseline, source mapping, requiredness rationale, metric meaning and limits;
  support automated acceptance verification and reviewer replay. (FR1–FR3, FR13–FR16, TR1)

## Data model changes

- **Evidence manifest:** bundle/contract/report versions; fixed inclusive dates
  `2026-09-01` and `2026-09-30`; source URL, recorded request parameters and
  retrieval timestamp; relative artifact references and SHA-256 hashes for the
  original national snapshot and supporting metadata/research. No run-time clock
  value participates in deterministic verification output. (FR1, FR3, FR13, TR1)
- **Source record:** immutable original JSON value plus snapshot hash and
  zero-based position in `response.data`. A record reference identifies invalid,
  duplicate and conflicting inputs as well as the selected row. (FR3, FR13)
- **National observation contract v1:** exactly the seven fields in the spec,
  all required strings, with no nullable modeled values. `period` is a real
  calendar date in the recorded `YYYY-MM-DD` format; measurements are finite
  base-ten numeric strings parsed without binary floating point; unit values
  are exactly `megawatts`, `megawatts` and `percent`. Empty/whitespace-only values,
  non-string values, malformed numbers/dates, non-finite numbers, unexpected
  attributes and nonpositive capacity are exclusions. Document this as the
  baseline application contract, not an upstream historical guarantee.
  (FR1, FR4–FR5, TR2)
- **Selected daily observation:** date, exact decimal capacity/outage/reported
  percentage, units, original source strings and selected record reference.
  Equality uses the complete parsed observation, including reported percentage
  and units; numerically equivalent decimal spellings compare equally while
  their original evidence remains intact. Select the greatest source position
  among usable records for a date before classifying earlier records. An earlier
  usable record equal to the winner is duplicate-collapsed; a different one is
  superseded. This handles repeated A/B/A values without losing the last winner.
  (FR7–FR8, FR11, FR13, TR2)
- **Daily result:** selected observation plus exact fractional share and exact
  percentage, each represented by integer numerator/positive denominator;
  calculated and reported percentage presentation strings have two decimals.
  Parse source values as `Decimal` and use exact rational arithmetic (`Fraction`)
  for division and rounding decisions, avoiding repeating-decimal loss and
  premature rounding. Apply decimal half-up rounding only to presentation.
  (FR9–FR11, TR2–TR3)
- **Verification report:** versions/evidence references; selected daily results;
  per-record disposition and exclusion reason codes with affected fields; unique
  excluded-row count and separate reason counts; received/selected/duplicate/
  superseded counts; 30 ordered calendar coverage entries; metric description and
  all FR16 limitations. Counts partition source rows; multiple reasons never
  multiply the excluded-row total. Missing results are null/unavailable, with
  either no observation or linked exclusions. Invalid dates stay in the global
  exclusion ledger and are never guessed into a date's coverage. Include no
  percentage-agreement classification or discrepancy diagnostics.
  (FR2, FR6, FR12–FR16, TR4)

No operational schema, persistence migration or published analytical schema is
introduced by this verification artifact model. (TR1; spec scope)

## Interfaces & contracts

- **RecordedEvidence port:** input is a bundle reference; output is the verified
  manifest, supporting documentation and ordered source records. Missing files,
  checksum mismatch, malformed JSON or an invalid response envelope fail the
  run explicitly; invalid observations inside a valid envelope proceed to row
  exclusion. There is no network, API-key or live-refresh fallback. (FR3–FR4, FR13, TR1)
- **VerifyNationalBaseline service:** input is the fixed-baseline evidence
  reference; output is a transport-independent verification report. Apply row
  validation before daily selection, then calculate and account for every
  baseline date. Neither a coverage gap nor a percentage difference alone is a
  verification error when represented according to the spec. Contract/version,
  evidence-integrity and arithmetic invariant failures are explicit errors.
  (FR4–FR16, TR1–TR4)
- **ReportWriter port:** input is a completed report and output destination;
  output is a machine-readable report plus a readable rendering with source
  links. Serialize decimals as original/exact decimal strings and rational
  numerators/denominators as integer strings; use explicit fraction/percentage
  labels. Report-write failures cannot return successful completion. Source
  artifacts are read-only and must never be output targets. (FR3, FR9, FR11–FR13, TR2–TR3)
- **Contributor command `verify-national-data`:** accept evidence-bundle and
  output-directory arguments, defaulting the former to the fixed checked-in
  baseline. Produce artifact locations and a success/nonzero failure outcome;
  expose no date-window or live-source option. Other explicitly identified
  bundles are for isolated tests of the same fixed interval, never silent
  substitutions for the real baseline. No HTTP endpoint, end-user identity or
  product data access is introduced. (FR13–FR16, TR1)

## Implementation phases

1. **Establish replayable evidence and contract** — preserve a byte-identical
   tracked copy of the sanitized national snapshot, a hashed manifest, recorded
   documentation and national contract v1. Requiredness derives from metadata
   plus the complete baseline field profile; document metric meaning and limits.
   A clean checkout has the inputs needed for offline verification.
   (FR1–FR3, FR13, FR16, TR1–TR2)
2. **Implement national policies** — validation, reason accounting, last-usable
   selection, duplicate handling, exact ratios and two-decimal presentation work
   through pure interfaces, with focused synthetic edge-case tests clearly
   distinguished from real EIA evidence. (FR4–FR12, FR15, TR2–TR4)
3. **Compose offline verification** — application orchestration, local adapters
   and CLI produce deterministic evidence-linked reports and full date coverage;
   startup/import boundaries and integrity errors are exercised.
   (FR3, FR6, FR11–FR16, TR1–TR4)
4. **Verify and document findings** — run the preserved baseline and independent
   arithmetic checks, review the resulting evidence/limitations, and record
   actual outcomes. Complete Ruff, mypy, pytest and architecture/startup checks
   using the repository's documented commands. (FR1–FR16, TR1–TR4, AC1–AC20)

## Dependencies & integrations

- Existing Python >=3.12 package, standard-library JSON/hash/decimal/rational
  support and repository Ruff/mypy/pytest tooling; no new runtime service or
  third-party analytical dependency is needed. (FR9, FR13, TR1–TR3)
- Recorded inputs: `data/exploration/eia-profile.json`, national metadata,
  capacity-semantics research and the profile's local `eia-samples/us.json`.
  During planning, the national snapshot was present with 30 rows and SHA-256
  `b140ed2d61813f500089704506a52518914cc3bce7c1859f90ab04c50ad54e9c`, matching
  the profile. It is currently Git-ignored: package only that sanitized national
  response into tracked verification evidence without changing its bytes/order.
  Profile calculations remain exploratory evidence, not the arithmetic oracle.
  (FR1, FR3, FR13–FR14, TR1)
- Preserve the recorded metadata/research and its source citations alongside
  the baseline. Existing generator examples support the accepted wording only;
  verification has no facility/generator dataset dependency or live-document
  retrieval step. (FR2, FR16, TR1)

## Risks & tradeoffs

- **Local-only evidence could disappear from a clean checkout** — retain the
  sanitized national baseline and manifest in version control, verify hashes,
  and fail explicitly on missing/corrupt evidence. (FR3, FR13, TR1)
- **The clean baseline cannot exercise exclusion/conflict policies** — use
  labeled synthetic cases and adversarial A/B/A ordering tests; never describe
  those cases as anomalies observed in real EIA records. (FR4–FR8, FR14–FR16)
- **Finite decimal division can hide precision or rounding errors** — retain
  exact rational results and source decimals; independently check arithmetic and
  exact halfway presentation boundaries. (FR9–FR11, TR2–TR3)
- **Recorded schema/meaning may be overgeneralized** — version the bounded
  contract, keep historical capacity vintage unverified, and report all stated
  limits; do not add outage/percentage range exclusions beyond agreed rules.
  (FR1–FR2, FR16, TR2–TR4)
- **CLI wiring could weaken existing import guardrails** — allow only a narrow
  CLI startup composition path and necessary pure/transport imports; extend
  negative fixtures and side-effect checks without broad handler access to
  bootstrap or infrastructure. (FR13, TR1)

### Alternatives considered

- Standalone verification script — rejected because it would duplicate future
  ingestion policies instead of providing reusable domain/application behavior.
  (FR1, FR4–FR10)
- Live retrieval or full S3/Parquet/PostgreSQL delivery — deferred because the
  fixed-evidence verification neither needs nor proves those integrations.
  (TR1; spec scope)
- Float/rounded-decimal-only results — rejected because they lose exact
  calculation evidence and can mishandle halfway presentation values. (TR3)

## Test strategy

- **AC1–AC2, AC16:** review contract and report text against recorded national
  metadata, field profile, research and accepted ADRs; assert required meaning,
  baseline dates, evidence identities and each limitation in the rendered report.
- **AC3, AC13:** adapter/integration tests verify original bytes, hashes and every
  source position; replay selections from the ledger, including excluded,
  repeated and conflicting synthetic records. Missing/corrupt bundles and
  malformed envelopes fail explicitly rather than appearing as ordinary gaps.
- **AC4–AC6:** parameterized domain tests for every required field, invalid
  shapes/dates/numbers/units, unknown attributes and capacity boundaries;
  multi-reason exclusions verify unique row counts and complete reason lists.
- **AC7–AC8:** domain tests cover identical records, equivalent decimal
  spellings, A/B/A conflicts, percentage-only conflicts, later invalid records
  and reordered processing with preserved source positions; exactly one last
  usable winner remains and disposition counts reconcile.
- **AC9–AC10, AC18–AC20:** verify all real-baseline ratios independently using
  integer-scaled source decimals and cross-multiplication. Synthetic tests cover
  zero outage, repeating fractions, high-precision inputs, halfway 1.235% →
  1.24%, neighboring rounding boundaries and unequal reported percentages.
  Deliberately incorrect arithmetic must fail the independent oracle; reported
  percentage disagreement must not. Assert selected source values survive unchanged.
- **AC11–AC12:** integration tests read serialized/rendered reports and check
  both percentages bind to the selected record, percentage labels/formatting,
  and absence of agreement/discrepancy fields or messages, including unequal inputs.
- **AC14–AC15:** service tests cover full, partial and empty usable coverage,
  all-invalid days and unassignable dates; every baseline calendar date appears
  once and unavailable results remain distinct from valid zero results.
- **AC17:** end-to-end CLI replay from a clean checkout with network access
  denied and changed clocks produces identical report content and source hashes.
  Confirm imports and construction perform no retrieval or verification work.
- Run the existing health, startup and architecture regression checks alongside
  new tests; extend narrow allowlists for `Fraction` and CLI transport/composition
  only. Passing these checks does not establish product authorization or SQL
  isolation, which remain outside this effort. (TR1; spec scope)

## Assumptions

- Source date/numeric/unit strings follow the narrow recorded contract. General
  coercion of future source types and extra physical measurement bounds are not
  inferred from this sample. (FR1, FR4–FR5, TR2)
- The existing sanitized response is the original recorded evidence available
  to this effort; the report does not claim to preserve the credential-bearing
  wire response or independently verify EIA/NRC physical measurements. (FR3, FR16)
- The contributor CLI and local report are verification delivery only. Future
  authenticated backend/refresh use cases may reuse the policies while enforcing
  their own accepted authorization, storage and publication boundaries. (TR1; spec scope)

## Open decisions

_None._
