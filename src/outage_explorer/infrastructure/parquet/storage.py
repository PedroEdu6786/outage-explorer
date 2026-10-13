"""Bounded Parquet encoding and verification over immutable local objects."""

import io
from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactKind,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.infrastructure.parquet.object_storage import LocalObjectStore
from outage_explorer.infrastructure.parquet.schemas import schema_for
from outage_explorer.infrastructure.parquet.value_bounds import value_size as value_size


class _LimitedBuffer(io.BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: Any) -> int:
        if self.tell() + len(data) > self.limit:
            raise ArtifactLimitError("Exceeded file bytes")
        return super().write(data)


class LocalParquetStore(LocalObjectStore):
    """Write and verify bounded Parquet files over one immutable staging session."""

    def adopt_exact(self, reference: ArtifactRef) -> None:
        """Charge an explicitly referenced existing file once, without listing.

        Reopened sessions start without an inventory. Verify the complete file
        before admitting it into the same aggregate budget as future writes and
        transient input. Repeated validation never double charges a digest.
        """
        self.verify(reference)
        with self._lock:
            if reference.object.key in self._objects:
                return
            if len(self._objects) >= self.bounds.objects:
                raise ArtifactLimitError("Exceeded object count")
            occupied_bytes = self._bytes + self._transient_bytes
            if occupied_bytes + reference.object.byte_count > self.bounds.total_bytes:
                raise ArtifactLimitError("Exceeded total bytes")
            self._objects.add(reference.object.key)
            self._bytes += reference.object.byte_count

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
            reference = self._write_batch(kind, grain, partition, batch, schema)
            references.append(reference)
        return tuple(references)

    def _row_batches(
        self, rows: Iterable[dict[str, object]]
    ) -> Iterator[list[dict[str, object]]]:
        """Group rows without exceeding either the row or byte budget."""
        row_limit = min(self.bounds.batch_rows, self.bounds.row_group_rows)
        batch: list[dict[str, object]] = []
        batch_bytes = 0
        for record in rows:
            self.check()
            record_bytes = value_size(record, self.bounds)
            if record_bytes > self.bounds.row_group_bytes:
                raise ArtifactLimitError("Exceeded row-group bytes")

            row_limit_reached = len(batch) >= row_limit
            would_exceed_bytes = (
                batch_bytes + record_bytes > self.bounds.row_group_bytes
            )
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
        if table.nbytes > self.bounds.row_group_bytes:
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
            buffer = _LimitedBuffer(self.bounds.file_bytes)
            pq.write_table(
                table,
                buffer,
                compression="NONE",
                use_dictionary=False,
                row_group_size=self.bounds.row_group_rows,
                write_statistics=False,
                write_page_checksum=True,
            )
            stored = self.put_immutable([buffer.getvalue()])
        except (pa.ArrowException, OverflowError, TypeError) as exc:
            raise ArtifactError("Cannot encode artifact using declared schema") from exc
        return ArtifactRef(stored, kind, grain, partition, len(rows))

    def write_file(
        self, kind: ArtifactKind, grain: Grain, rows: Iterable[dict[str, object]]
    ) -> ArtifactRef:
        """Write all rows as exactly one immutable object of bounded row groups.

        Each batch becomes one row group, so decode bounds match ``write``. Public
        files keep column statistics for row-group pruning. Row order is the
        caller's; ordering rules belong to the modeling and verification steps.
        """
        schema = schema_for(kind, grain)
        buffer = _LimitedBuffer(self.bounds.file_bytes)
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
                        row_group_size=self.bounds.row_group_rows,
                    )
                    total_rows += len(batch)
            if total_rows == 0:
                raise ArtifactError("Empty dataset file")
            stored = self.put_immutable([buffer.getvalue()])
        except (pa.ArrowException, OverflowError, TypeError) as exc:
            raise ArtifactError("Cannot encode artifact using declared schema") from exc
        return ArtifactRef(stored, kind, grain, None, total_rows)

    def _parquet(self, reference: ArtifactRef) -> Any:
        if reference.schema_version != "1":
            raise ArtifactError("Invalid artifact version or row count")
        if type(reference.row_count) is not int or reference.row_count <= 0:
            raise ArtifactError("Invalid artifact version or row count")
        source = pq.ParquetFile(
            self._path(reference.object),
            pre_buffer=False,
            page_checksum_verification=True,
            thrift_string_size_limit=self.bounds.file_bytes,
            thrift_container_size_limit=self.bounds.row_group_bytes,
        )
        try:
            expected_schema = schema_for(reference.kind, reference.grain)
            if not source.schema_arrow.equals(expected_schema, check_metadata=True):
                raise ArtifactError("Physical schema mismatch")
            metadata = source.metadata
            if metadata.num_rows != reference.row_count:
                raise ArtifactError("Artifact row count mismatch")
            for index in range(metadata.num_row_groups):
                group = metadata.row_group(index)
                if group.num_rows > self.bounds.row_group_rows:
                    raise ArtifactLimitError("Parquet row group exceeds decode bounds")
                if group.total_byte_size > self.bounds.row_group_bytes:
                    raise ArtifactLimitError("Parquet row group exceeds decode bounds")
        except Exception:
            source.close()
            raise
        return source

    def verify(self, reference: ArtifactRef | StoredObject) -> None:
        if isinstance(reference, StoredObject):
            self.verify_object(reference)
            return
        self.verify_object(reference.object)
        try:
            with self._parquet(reference) as source:
                count = 0
                for batch in source.iter_batches(
                    batch_size=self.bounds.batch_rows, use_threads=False
                ):
                    if batch.nbytes > self.bounds.row_group_bytes:
                        raise ArtifactLimitError("Decoded batch exceeds bytes")
                    self.check()
                    for record in batch.to_pylist():
                        value_size(record, self.bounds)
                    count += batch.num_rows
                if count != reference.row_count:
                    raise ArtifactError("Decoded artifact row count mismatch")
        except (pa.ArrowException, OSError) as exc:
            raise ArtifactError("Unreadable Parquet artifact") from exc

    def records(self, reference: ArtifactRef) -> Iterator[dict[str, object]]:
        # Full verification precedes the first yield, including truncated consumers.
        self.verify(reference)
        with self._parquet(reference) as source:
            for batch in source.iter_batches(
                batch_size=self.bounds.batch_rows, use_threads=False
            ):
                self.check()
                yield from cast(list[dict[str, object]], batch.to_pylist())
