# ADR-0040: Defer a status card for newly published data

Status: **Accepted future improvement; deferred until current work is complete**

Date: 2026-10-04

## Context

After a successful publication, the backend automatically serves new reads
from the active snapshot. An already open view or query result can still be
bound to the previous snapshot. The user requested a future status card to
indicate that a new data version is available and offer a refresh.

## Decision

- Record this as an improvement for after the current agreed implementation
  is finished. It is not a requirement or blocker for the current delivery.
- When the displayed data belongs to an older snapshot than the active one,
  show a status card indicating that newer published data is available and
  offer an explicit action to refresh the view.
- Refreshing the view requests data from the backend's active snapshot. The
  backend chooses that snapshot; this is not a version-selection interface.
- This action does not start EIA ingestion or approve publication. Admin
  ingestion and automatic publication keep their existing behavior.
- Keep existing preview continuations and SQL result pages bound to their
  original snapshot/execution. For SQL, obtaining updated results requires an
  explicit new execution with a new query ID; neither the card appearing nor
  pagination silently reruns SQL.

## Consequences and open details

The separate UI client owns the card and its interaction. Snapshot metadata,
change detection, notification transport, placement, wording, and handling of
an ongoing query remain future design work. No polling, push mechanism, new
endpoint, or implementation is selected by this note.

The card helps users notice that their displayed results predate a publication
while preserving stable pagination. New reads continue to receive the current
active snapshot automatically even before this improvement is implemented.

## References

- [Automatic refresh publication](0003-admin-refresh-publication.md)
- [Snapshot-bound preview pagination](0015-dataset-preview-pagination.md)
- [Single-execution query results](0020-paginate-query-results.md)
- [Separate UI client](0039-separate-ui-client-atomic-design.md)
- [UI delivery and deferred improvements](../context/ui-client/05-delivery-and-acceptance.md)
