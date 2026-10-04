# ADR-0041: Typed connector defaults and optional JSON configuration

Status: **Accepted by user direction**

Date: 2026-10-04

## Context

Phase 4 required four environment variables containing complete resource budgets.
The user requested typed defaults with CLI overrides, preferring a JSON document
supplied by a flag. Mandatory environment JSON makes ordinary local runs cumbersome.

## Decision

Keep immutable typed defaults in `settings.py` and accept an optional
`--config PATH` UTF-8 JSON object. It may provide `start`, `end`, `staging`,
`prior`, `source`, `artifact`, `model`, and `report_bytes`. Resource sections
override individual default fields; omitted fields retain defaults. Explicit
date/staging/prior flags override corresponding file values. Effective dates and
staging remain required; there is no automatic date selection or active pointer.

Remove `OUTAGE_CONNECTOR_*` environment overrides. `EIA_API_KEY` remains required
in the process environment and is not accepted in JSON or CLI arguments. Do not
load `.env` automatically. Reject malformed, duplicate or unknown keys, invalid
types and nonpositive budgets. Read at most 64 KiB of configuration plus one byte
to detect overflow. Validate before creating staging storage or HTTP transports;
help and imports do not read the configuration file. Errors omit user values.

Retain phase-4 example limits as initial defaults rather than introducing
unmeasured larger resource allowances. They are conservative starting values,
not a claim of production readiness or support for the full initial interval.
Bootstrap still translates configuration into existing validated bounded ports.

## Alternatives and consequences

- Required environment JSON is explicit but difficult to maintain and inspect.
- A flag for every limit is discoverable but adds dozens of CLI options.
- One optional JSON file groups overrides and is reproducible; defaults permit
  simpler runs. The file contains nonsecret configuration only.
- Legacy budget environment variables no longer affect execution; move overrides
  into JSON. Limits remain enforced, and live sizing still belongs to phase 6.

This changes contributor configuration only. It does not authorize live requests,
implement S3 durability, or change publication and authorization boundaries.
