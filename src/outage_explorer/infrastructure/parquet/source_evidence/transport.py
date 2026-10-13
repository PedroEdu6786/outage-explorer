"""Match bounded transient request audits to accepted source pages."""

from typing import cast

from outage_explorer.application.ports.artifacts import ArtifactError
from outage_explorer.application.ports.candidates import SanitizedPage
from outage_explorer.infrastructure.parquet.source_evidence.validation import (
    audit_descriptor,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


class TransportWindow:
    def __init__(self) -> None:
        self.audits: dict[str, dict[str, object]] = {}
        self.matched: set[str] = set()
        self.used_requests: set[str] = set()

    def accept(self, page: SanitizedPage, store: LocalParquetStore) -> int:
        """Account audit bytes and match this page to its canonical request."""
        byte_count = 0
        if page.transport:
            if len(page.transport) > 3 or set(self.audits) != self.matched:
                raise ArtifactError("Unmatched or oversized transient transport window")
            self.audits, self.matched = {}, set()
            for item in page.transport:
                audit, size = audit_descriptor(item, store.bounds)
                store.account_transient(size)
                byte_count += size
                request_id = cast(str, audit["request_id"])
                if audit["used"]:
                    if request_id in self.used_requests:
                        raise ArtifactError("Repeated transient used request")
                    self.used_requests.add(request_id)
                    self.audits[request_id] = audit
        if self.audits:
            self._match(page)
        return byte_count

    def _match(self, page: SanitizedPage) -> None:
        canonical = self.audits.get(page.origin.request_id)
        if canonical is None:
            raise ArtifactError("Missing transient canonical request")
        response = cast(
            dict[str, object],
            cast(dict[str, object], canonical["envelope"])["response"],
        )
        if (
            canonical["offset"] != page.offset
            or canonical["parameters"] != page.parameters
            or canonical["attempt"] != page.attempt
            or canonical["received_at"] != page.origin.retrieved_at.isoformat()
            or response.get("total") != page.source_total
            or response["data"] != list(page.values)
        ):
            raise ArtifactError("Transient canonical transport mismatch")
        self.matched.add(page.origin.request_id)

    def finish(self) -> None:
        if set(self.audits) != self.matched:
            raise ArtifactError("Unmatched transient transport window")
