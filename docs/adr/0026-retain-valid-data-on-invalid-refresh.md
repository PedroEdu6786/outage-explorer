# ADR-0026: Retain existing valid data when refreshed records are invalid

Status: **Accepted; seed provisioning and merge mechanics pending**

Date: 2026-10-01

## Context

The user resolved the all-excluded and invalid-replacement cases left open in
ADR-0023/0024. Normal refresh operation assumes initial analytical data has
already been seeded. This is separate from provisioning seeded login accounts.

## Decision

- If every incoming record is excluded, keep the currently published data
  unchanged. Do not publish an empty replacement. Show the errors and exclusion
  reasons in the Admin quality report, explicitly stating that existing data
  was retained and no new data was published.
- If an invalid incoming record replaces an identifiable older valid
  observation, exclude the incoming record and keep the older valid row.
  Other valid observations may still be updated through normal publication.
- A valid newer observation still replaces an older one under ADR-0024.
  Invalid observations without an older match remain excluded.
- Preserve retained rows' original provenance; do not claim they were freshly
  validated source observations. Report retained older rows separately from
  newly accepted records and explain why they were kept.
- Assume valid initial analytical data is seeded before normal refresh use.
  Seed data must follow the existing real-EIA evidence and schema-contract
  requirements. This decision does not perform seeding or select its mechanism.

This resolves the corresponding open policies in ADR-0023/0024 and extends the
accepted quality-report outcome in ADR-0025. Automatic successful publication
and continued access to existing snapshots remain unchanged.

## Alternatives and consequences

Publishing an empty replacement or deleting an older valid row because its
replacement is invalid would discard usable data. Keeping it prioritizes
continuity but can leave some observations older than the latest refresh;
quality reporting and retained provenance must make that visible.

The proposed interval-replacement implementation must merge retained older
rows with accepted new rows before enforcing uniqueness and publishing. Raw
exclusion counts and retained-old-row counts describe different sets and must
not be conflated with the final modeled-row total.

Exact status codes, seed provisioning and merge implementation remain open.
Matching requires a trustworthy observation key; do not invent a match when
an invalid record lacks one. In particular, exclusion is not proof of source
deletion. Genuine source absence and zero records returned by EIA remain
separate completeness cases; this decision covers records actually excluded
by validation.

- [Backend spec](../specs/outage-explorer-backend/spec.md)
- [Backend plan](../specs/outage-explorer-backend/plan.md#refresh-and-publication)
