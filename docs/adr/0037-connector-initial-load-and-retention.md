# ADR-0037: Connector initial live load and retained-data publication

Status: **Accepted**

Date: 2026-10-02

## Context

The connector drafts left initial loading, absent source keys and partial-route
exclusion outcomes open. An automatic devlog entry recorded earlier agreements,
but that entry was not independent confirmation. The user explicitly confirmed
"Sí, aplica las decisiones del devlog" when asked to resolve the discrepancy.
This decision records that current authorization while preserving historical ADRs.

## Decision

- Use **2026-04-02 through 2026-10-01, inclusive**, for the initial live load.
  Subsequent refreshes use explicit bounded intervals; no automatic rolling
  anchor or latest-30-day policy is selected.
- If an older valid key is absent from a later successfully retrieved interval,
  keep its value and original provenance, report it as retained because absent,
  and allow other valid changes to publish. Absence is distinct from an invalid
  replacement and never implies source deletion.
- If one or some datasets have nonempty incoming observations that are all
  excluded, retain those datasets' complete previous valid data and allow valid
  changes from the other datasets to publish. If all three incoming datasets
  are entirely excluded, keep the active generation unchanged and explicitly
  report no publication.
- With no previous generation, retrieve the initial interval live through the
  same validation, selection, artifact verification and publication pipeline as
  refresh. Every one of the three datasets must produce usable output before
  initial publication. There is no separate mandatory September-bundle seed.
- Preserve typed decimal analytical values alongside original numeric strings
  and exact calculation evidence. Values unsupported by the chosen physical
  representation cause an explicit candidate/publication failure rather than
  silent rounding, truncation or an ordinary source-row exclusion. Concrete
  widths, scales and adapter libraries remain implementation verification work.
- Empty required routes, failed or missing pages, unusable envelopes, exhausted
  bounds and storage-integrity failures remain run failures. Retention does not
  make unsuccessful retrieval publishable. The facility advertised/received
  discrepancy remains a visible, deferred diagnostic that alone is nonblocking.

## Consequences and scope

This supersedes only ADR-0026's assumption that valid analytical seed data must
already exist before the connector can operate. Its all-excluded and
identifiable-invalid retention policies remain accepted. The new absent-key and
partial-dataset rules extend those policies without changing source contracts,
grain independence, immutable provenance or atomic complete-generation publication.

Quality accounting separates newly selected rows, retained-invalid rows,
retained-absent rows and rows carried outside the interval. Report full-dataset
retention without double-counting those categories. A retained row is never
reported as freshly retrieved or freshly validated.

Q2 and Q5 product decisions are resolved. Resource measurements, live pagination
and ordering, contract applicability across the initial interval, concrete
dependencies and runtime integration remain engineering gates. Acceptance of
these policies does not establish live evidence, authorize deployment or perform
external publication. September bundles remain offline verification evidence.

## References

- [Connector specification](../specs/data-connector/spec.md)
- [Connector plan](../specs/data-connector/plan.md)
- [ADR-0026: Retain existing valid data](0026-retain-valid-data-on-invalid-refresh.md)
- [ADR-0024: Duplicates and revisions](0024-collapse-duplicates-and-use-latest-values.md)
- [ADR-0010: Deferred retention policy](0010-defer-retention-policy.md)
