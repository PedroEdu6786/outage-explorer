# ADR-0069: Dynamic end for the first refresh

Status: **Accepted by user direction**

Date: 2026-10-10

## Context

The user identified that a fixed October 1 end-date validation conflicts with
the dynamic UTC end used at HTTP admission. ADR-0063 had retained the older
first-load exception; ADR-0068 preserved that check during the Pydantic migration.

## Decision

- Supersede the fixed initial end-date requirement for product refreshes. The
  first refresh also uses the UTC end date resolved and saved at admission.
- Keep the initial start-date requirement of April 2, 2026. This correction is
  scoped to the end date; subsequent refresh starts remain operator-configured.
- Execution and publication use the saved end, including after midnight; they
  never compare it with a fresh clock reading or the historical October 1 date.
- Preserve inclusive interval limits, all-grain usability, non-date resource
  bounds, idempotent replay and ownership checks. Connector CLI behavior is unchanged.

No data reset, worker restart, live initial load or publication is authorized.
