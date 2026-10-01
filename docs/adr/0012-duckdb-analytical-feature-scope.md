# ADR-0012: Target broad DuckDB analytical feature support

Status: **Accepted direction; compatibility unverified**

Date: 2026-10-01

## Context and decision

The user requests DuckDB's accepted SQL features, with appropriate errors for
unsupported queries and feature exclusions only as concrete issues emerge.
Target the pinned DuckDB version's read-only analytical syntax and functions
over authorized product datasets. Do not preemptively exclude recursive CTEs,
set operations or other analytical forms simply to simplify validation.

Existing role authorization, read-only access and resource limits still apply.
Writes, configuration changes, arbitrary external sources, engine internals
and extension loading are not newly authorized by this analytical scope.

## Alternatives and consequences

A small hand-picked syntax subset would simplify implementation but contradict
the requested exploration scope. Broad support requires testing composed
queries and revisiting a candidate parser if it rejects valid analytical SQL.
SQLGlot remains a candidate, not the definition of the product's dialect.

Unknown data access must still fail closed. Document demonstrated compatibility
limitations with an example and reason, and report them as exclusions rather
than silently claiming complete DuckDB compatibility. No runtime proof exists.

Use stable errors for invalid SQL, unsupported features, denied data access,
resource limits and unavailable data. Preserve useful query diagnostics while
omitting credentials, private paths and unauthorized schema details. Exact
HTTP mappings remain design choices.
