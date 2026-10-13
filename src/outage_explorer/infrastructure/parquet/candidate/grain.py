"""Build and replay-verify one local resource Parquet file."""

import logging
from collections.abc import Iterator
from datetime import date
from itertools import chain, zip_longest

from outage_explorer.application.ports.artifacts import ArtifactError, ArtifactRef
from outage_explorer.application.ports.candidates import GrainSummary, TransientInput
from outage_explorer.domain.refresh import (
    IncomingRow,
    ModeledPartition,
    Quality,
    RefreshBounds,
    RefreshInputError,
    merge_partition,
    model_partition,
)
from outage_explorer.infrastructure.parquet.candidate.accounting import (
    CandidateAccounting,
)
from outage_explorer.infrastructure.parquet.partitions import (
    DayMerge,
    day_walk,
    prior_days,
    row_day,
)
from outage_explorer.infrastructure.parquet.schemas import modeled_record
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

_LOG = logging.getLogger("outage_explorer.connector.parquet")


class ParquetGrainBuilder:
    """Own the source-to-file lifecycle and replay check for one grain."""

    def __init__(self, store: LocalParquetStore) -> None:
        self.store = store

    def build(
        self,
        item: TransientInput,
        bounds: RefreshBounds,
        prior: ArtifactRef | None,
    ) -> tuple[ArtifactRef, GrainSummary]:
        _LOG.info("resource_build_started grain=%s", item.grain)
        staged = self._group_source_rows_by_day(item)
        account = CandidateAccounting(item.grain)

        # Finish accounting/eligibility before committing a grain to a file.
        stream = self._modeled_records(item, staged, prior, bounds, account)
        first = next(stream, None)
        if first is None:
            raise RefreshInputError(
                "Initial load requires usable output in all three grains"
            )
        ref = self.store.write_file("resource", item.grain, chain((first,), stream))
        summary = account.summary()
        self._verify_written_grain(item, staged, prior, bounds, ref, summary)
        _LOG.info("resource_verify_complete grain=%s", item.grain)
        return ref, summary

    def _verify_written_grain(
        self,
        item: TransientInput,
        staged: dict[date | None, tuple[IncomingRow, ...]],
        base: ArtifactRef | None,
        bounds: RefreshBounds,
        ref: ArtifactRef,
        summary: GrainSummary,
    ) -> None:
        replay = CandidateAccounting(item.grain)
        expected = self._modeled_records(item, staged, base, bounds, replay)
        for actual, wanted in zip_longest(self.store.records(ref), expected):
            if actual != wanted:
                raise ArtifactError("Resource values disagree with transient merge")
        if replay.summary() != summary or ref.row_count != summary.candidate_count:
            raise ArtifactError("Resource quality/coverage does not reconcile")

    def _modeled_records(
        self,
        item: TransientInput,
        staged: dict[date | None, tuple[IncomingRow, ...]],
        base: ArtifactRef | None,
        bounds: RefreshBounds,
        account: CandidateAccounting,
    ) -> Iterator[dict[str, object]]:
        for part in self._merged_days(item, staged, base, bounds):
            account.add(part, bounds)
            for row in part.merged.rows:
                yield modeled_record(row)

    def _group_source_rows_by_day(
        self, item: TransientInput
    ) -> dict[date | None, tuple[IncomingRow, ...]]:
        staged: dict[date | None, list[IncomingRow]] = {}
        retrieval_id: str | None = None
        seen_page_positions: set[tuple[int, int]] = set()
        for position, row in enumerate(item.rows):
            self.store.check()
            retrieval_id = self._validate_source_row(
                item, row, position, seen_page_positions, retrieval_id
            )
            day = row_day(row)
            if day is not None and not item.interval.contains(day):
                raise RefreshInputError("Source observation outside requested interval")
            staged.setdefault(day, []).append(row)
        return {day: tuple(rows) for day, rows in staged.items()}

    @staticmethod
    def _validate_source_row(
        item: TransientInput,
        row: IncomingRow,
        position: int,
        seen_page_positions: set[tuple[int, int]],
        retrieval_id: str | None,
    ) -> str:
        origin = row.origin
        page_position = origin.page_index, origin.row_index
        ordered = (
            origin.source_position == position
            and page_position not in seen_page_positions
        )
        same_source = (
            origin.grain,
            origin.run_id,
            origin.contract_id,
            origin.transformation_id,
        ) == (
            item.grain,
            item.run_id,
            item.contract_id,
            item.transformation_id,
        )
        same_retrieval = retrieval_id is None or retrieval_id == origin.retrieval_id
        if not (ordered and same_source and same_retrieval):
            raise ArtifactError("Transient source identity/order mismatch")
        seen_page_positions.add(page_position)
        return origin.retrieval_id

    def _merged_days(
        self,
        item: TransientInput,
        staged: dict[date | None, tuple[IncomingRow, ...]],
        prior: ArtifactRef | None,
        bounds: RefreshBounds,
    ) -> Iterator[DayMerge]:
        for position, (day, old) in enumerate(
            day_walk(
                item.interval, prior_days(self.store, prior, bounds, resource=True)
            )
        ):
            self.store.check()
            if position % 14 == 0 or day == item.interval.end:
                _LOG.info(
                    "resource_merge_progress grain=%s partition=%s", item.grain, day
                )
            incoming = self._model_incoming_day(item, staged.get(day, ()), bounds)
            yield DayMerge(day, merge_partition(incoming, old, bounds), old)

    @staticmethod
    def _model_incoming_day(
        item: TransientInput, rows: tuple[IncomingRow, ...], bounds: RefreshBounds
    ) -> ModeledPartition:
        if rows:
            return model_partition(item.grain, item.interval, rows, bounds)
        return ModeledPartition(
            grain=item.grain,
            interval=item.interval,
            rows=(),
            decisions=(),
            excluded_keys=frozenset(),
            observed_identities=frozenset(),
            observed_dates=frozenset(),
            quality=Quality(0, 0, 0, 0, 0, ()),
        )
