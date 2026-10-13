"""Bounded row groups and Parquet encoding for immutable local files."""

import io
from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactKind,
    ArtifactLimitError,
    ArtifactRef,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.infrastructure.parquet.object_storage import LocalObjectStore
from outage_explorer.infrastructure.parquet.schemas import schema_for
from outage_explorer.infrastructure.parquet.value_bounds import value_size


class _LimitedBuffer(io.BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: Any) -> int:
        if self.tell() + len(data) > self.limit:
            raise ArtifactLimitError("Exceeded file bytes")
        return super().write(data)


class ParquetFileWriter:
    """Encode rows using one local store's bounds and immutable object writer."""

    def __init__(self, store: LocalObjectStore) -> None:
        self.store = store

    def write(
        self,
        kind: ArtifactKind,
        grain: Grain,
        partition: date | None,
        rows: Iterable[dict[str, object]],
    ) -> tuple[ArtifactRef, ...]:
        schema = schema_for(kind, grain)
        references = []
        for batch in self._row_batches(rows):
            references.append(self._write_batch(kind, grain, partition, batch, schema))
        return tuple(references)

    def _row_batches(
        self, rows: Iterable[dict[str, object]]
    ) -> Iterator[list[dict[str, object]]]:
        """Group rows without exceeding either the row or byte budget."""
        bounds = self.store.bounds
        row_limit = min(bounds.batch_rows, bounds.row_group_rows)
        batch: list[dict[str, object]] = []
        batch_bytes = 0
        for record in rows:
            self.store.check()
            record_bytes = value_size(record, bounds)
            if record_bytes > bounds.row_group_bytes:
                raise ArtifactLimitError("Exceeded row-group bytes")

            row_limit_reached = len(batch) >= row_limit
            would_exceed_bytes = batch_bytes + record_bytes > bounds.row_group_bytes
            if batch and (row_limit_reached or would_exceed_bytes):
                yield batch
                batch = []
                batch_bytes = 0

            batch.append(record)
            batch_bytes += record_bytes
        if batch:
            yield batch

    def _table(self, rows: list[dict[str, object]], schema: Any) -> Any:
        table = pa.Table.from_pylist(rows, schema=schema)
        if table.nbytes > self.store.bounds.row_group_bytes:
            raise ArtifactLimitError("Exceeded encoded row-group bytes")
        if table.to_pylist() != rows:
            raise ArtifactError("Physical conversion changed artifact values")
        return table

    def _write_batch(
        self,
        kind: ArtifactKind,
        grain: Grain,
        partition: date | None,
        rows: list[dict[str, object]],
        schema: Any,
    ) -> ArtifactRef:
        try:
            table = self._table(rows, schema)
            buffer = _LimitedBuffer(self.store.bounds.file_bytes)
            pq.write_table(
                table,
                buffer,
                compression="NONE",
                use_dictionary=False,
                row_group_size=self.store.bounds.row_group_rows,
                write_statistics=False,
                write_page_checksum=True,
            )
            stored = self.store.put_immutable([buffer.getvalue()])
        except (pa.ArrowException, OverflowError, TypeError) as exc:
            raise ArtifactError("Cannot encode artifact using declared schema") from exc
        return ArtifactRef(stored, kind, grain, partition, len(rows))

    def write_file(
        self, kind: ArtifactKind, grain: Grain, rows: Iterable[dict[str, object]]
    ) -> ArtifactRef:
        """Write one object with bounded row groups in caller supplied order."""
        schema = schema_for(kind, grain)
        buffer = _LimitedBuffer(self.store.bounds.file_bytes)
        total_rows = 0
        try:
            with pq.ParquetWriter(
                buffer,
                schema,
                compression="NONE",
                use_dictionary=False,
                write_statistics=kind in ("public", "resource"),
                write_page_checksum=True,
            ) as writer:
                for batch in self._row_batches(rows):
                    writer.write_table(
                        self._table(batch, schema),
                        row_group_size=self.store.bounds.row_group_rows,
                    )
                    total_rows += len(batch)
            if total_rows == 0:
                raise ArtifactError("Empty dataset file")
            stored = self.store.put_immutable([buffer.getvalue()])
        except (pa.ArrowException, OverflowError, TypeError) as exc:
            raise ArtifactError("Cannot encode artifact using declared schema") from exc
        return ArtifactRef(stored, kind, grain, None, total_rows)
