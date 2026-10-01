# ADR-0015: Accept dataset preview pagination defaults

Status: **Accepted**

Date: 2026-10-01

## Context and decision

The user accepted the proposed dataset browsing behavior:

- Default preview page size: 100 rows; configurable maximum initially 500.
- Return an opaque continuation cursor bound to the caller, dataset,
  normalized filters, deterministic ordering and original snapshot.
- Keep subsequent pages on that snapshot even if refresh publishes another.
- Expire the browsing cursor 15 minutes after the first page, independently
  of the login session. Continuation does not renew cursor expiry.
- An expired cursor requires restarting browsing; never silently switch
  snapshots. Authenticate and authorize every page under current policy.

## Alternatives and consequences

Unbounded previews consume unpredictable resources. Paging across changing
snapshots can skip or repeat observations. Bounded pages and snapshot-bound
cursors avoid those problems; expired browsing sequences must restart.
Ordering keys depend on verified source models. This does not add SQL-result
pagination or change ADR-0013's SQL output limits. Error shape and oversized
page-request handling remain API design details.
