# ADR-0068: Declarative refresh configuration validation

Status: **Accepted by user direction**

Date: 2026-10-10

## Context

The user rejected both a compound validation predicate and its extraction into
several helpers, and explicitly selected the proposed Pydantic model. Constraints
should be visible beside the fields rather than encoded in procedural guards.

## Decision

- Use a frozen, strict Pydantic model for `RefreshConfiguration`, with positive
  integer limits, bounded S3 workers and a literal contract version.
- Validate field constraints and inclusive date relationships at construction,
  including reconstruction from stored configuration. Reject unknown fields.
- Keep the state-dependent initial-load policy in `validate_for_run(initial=...)`.
  Admission, execution and publication still enforce that policy.
- Use named construction arguments and `model_dump(mode="json")` for storage.
  Existing stored field names and ISO date representations remain unchanged.
- Permit only `BaseModel`, `ConfigDict`, `Field` and `model_validator` imports in
  `domain/refresh_configuration.py`. This is a narrow exception to ADR-0030's
  standard-library-only domain dependency rule; it grants no framework or I/O
  dependency elsewhere. Import-boundary tests enforce the exception.

## Consequences

Pydantic and its resolved dependencies become runtime requirements. Invalid
configurations fail earlier, with structured field errors, rather than waiting
for an explicit validation call. Callers must reconstruct through validation when
changing values; `model_construct` and unchecked `model_copy(update=...)` are not
used. The model remains immutable. Historical malformed configurations now fail
on read; valid historical JSON needs no migration.

A builder would organize construction steps but would still need these validation
rules. Plain helper methods preserved behavior but did not meet the user's
readability preference.
