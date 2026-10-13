"""Collect bounded, replayable source rows from sanitized pages."""

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import replace

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.candidates import SanitizedPage, TransientInput
from outage_explorer.domain.refresh import IncomingRow
from outage_explorer.infrastructure.parquet.source_evidence.transport import (
    TransportWindow,
)
from outage_explorer.infrastructure.parquet.source_evidence.validation import (
    check_page,
    validate_json_types,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.parquet.value_bounds import value_size


class _EvidenceCollector:
    def __init__(self, store: LocalParquetStore) -> None:
        self.store = store
        self.first: SanitizedPage | None = None
        self.rows: list[IncomingRow] = []
        self.seen: set[tuple[str, str]] = set()
        self.retrieval: tuple[str, ...] | None = None
        self.transport = TransportWindow()
        self.byte_count = 0
        self.page_count = 0
        self.terminal = False

    def accept(self, page: SanitizedPage, index: int) -> None:
        self.store.check()
        if index >= self.store.bounds.objects:
            raise ArtifactLimitError("Exceeded transient page count")
        if self.terminal:
            raise ArtifactError("Page follows empty terminal page")
        if self.first is None:
            self.first = page
        self.retrieval = check_page(
            page,
            self.first.interval,
            self.first.origin.grain,
            index,
            len(self.rows),
            self.retrieval,
            self.seen,
        )
        self.page_count += 1
        self._account_metadata(page)
        self.byte_count += self.transport.accept(page, self.store)
        self._collect_rows(page)
        if self.byte_count > self.store.bounds.total_bytes:
            raise ArtifactLimitError("Exceeded transient input bytes")
        self.terminal = not page.values

    def _account_metadata(self, page: SanitizedPage) -> None:
        for value in (
            page.parameters,
            page.metadata,
            page.route,
            page.api_version,
            page.source_total,
        ):
            size = value_size(value, self.store.bounds)
            validate_json_types(value, self.store.bounds)
            self.store.account_transient(size)
            self.byte_count += size

    def _collect_rows(self, page: SanitizedPage) -> None:
        for row_index, value in enumerate(page.values):
            self.store.check()
            size = value_size(value, self.store.bounds) + value_size(
                vars(page.origin), self.store.bounds
            )
            validate_json_types(value, self.store.bounds)
            self.store.account_transient(size)
            self.byte_count += size
            if self.byte_count > self.store.bounds.total_bytes:
                raise ArtifactLimitError("Exceeded transient input bytes")
            self.rows.append(
                IncomingRow(
                    replace(
                        page.origin,
                        row_index=row_index,
                        source_position=len(self.rows),
                    ),
                    deepcopy(value),
                )
            )

    def finish(self) -> TransientInput:
        first = self.first
        if first is None:
            raise ArtifactError("Input needs at least one accepted page")
        if not self.terminal:
            raise ArtifactError("Missing empty terminal source page")
        self.transport.finish()
        return TransientInput(
            first.origin.grain,
            first.interval,
            tuple(self.rows),
            self.page_count,
            self.byte_count,
            first.origin.run_id,
            first.origin.contract_id,
            first.origin.transformation_id,
        )


def collect_resources(
    store: LocalParquetStore, pages: Iterable[SanitizedPage]
) -> TransientInput:
    """Validate each complete source walk, keeping only bounded copied input rows.

    Page/transport metadata is checked as it arrives and discarded; no source,
    page, disposition, ledger or manifest object is installed in the store.
    """
    collector = _EvidenceCollector(store)
    for index, page in enumerate(pages):
        collector.accept(page, index)
    return collector.finish()
