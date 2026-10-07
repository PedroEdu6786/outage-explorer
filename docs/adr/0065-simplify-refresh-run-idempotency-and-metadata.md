# ADR-0065: Simplify refresh-run idempotency and metadata

Status: **Accepted** (explicit user direction, October 7, 2026)

## Context

The schema audit found that `refresh_runs.updated_at` has no downstream consumer.
`operation` is always `refresh`, and `request_identity` is always `refresh:v1:{}`:
the refresh endpoint accepts an empty body and no caller date/config overrides.
The user directed updating the entities and database after reviewing these three
cleanup candidates.

## Decision

Migration `0006_simplify_refresh_runs` removes all three columns. Remove their
entity fields, SQL writes and request-identity port arguments. Idempotency is
uniquely scoped to `(requester_id, key_digest)` within the refresh-only table.
Repeating a key returns the same admitted run and its frozen configuration, even
when current configuration or the date changes. A different key still respects
the single active refresh limit. Authorization and empty-body validation precede
lookup. There is no request-body identity comparison because no variable body is
accepted.

Replace the admission-immutability trigger function to reference only remaining
columns. Preserve its protection of identity, requester, key, configuration, base
generation and admission time, and its ban on deleting refresh/publication history.
Keep actual admission/start/finish timestamps, statuses, quality and ownership.

## Consequences

Existing runs, their frozen configurations, publication references and coordination
pointers remain unchanged. Dropping the constant operation dimension does not
merge formerly distinct keys: its database check allowed only `refresh`.
Downgrade refuses to fabricate discarded request identities or update timestamps.

The current endpoint cannot produce conflicting payload reuse of a key: nonempty
bodies are invalid. Public error schemas retain the existing conflict code for
contract stability, but this admission path no longer emits it. A future endpoint
accepting caller parameters must make an explicit idempotency decision.

The user also authorized applying pending migrations to the configured database.
Coordinate the API code update with migration while refresh is idle; do not reset
the active pointer, delete historical rows or retrieve new source data.
