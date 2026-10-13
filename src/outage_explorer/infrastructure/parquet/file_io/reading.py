"""Physical Parquet verification and bounded record iteration."""

from collections.abc import Iterator
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
)
from outage_explorer.infrastructure.parquet.object_storage import LocalObjectStore
from outage_explorer.infrastructure.parquet.schemas import schema_for
from outage_explorer.infrastructure.parquet.value_bounds import value_size


class ParquetFileReader:
    """Check physical files and stream records after store verification."""

    def __init__(self, store: LocalObjectStore) -> None:
        self.store = store

    def _parquet(self, reference: ArtifactRef) -> Any:
        if reference.schema_version != "1":
            raise ArtifactError("Invalid artifact version or row count")
        if type(reference.row_count) is not int or reference.row_count <= 0:
            raise ArtifactError("Invalid artifact version or row count")
        bounds = self.store.bounds
        source = pq.ParquetFile(
            self.store._path(reference.object),
            pre_buffer=False,
            page_checksum_verification=True,
            thrift_string_size_limit=bounds.file_bytes,
            thrift_container_size_limit=bounds.row_group_bytes,
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
                if group.num_rows > bounds.row_group_rows:
                    raise ArtifactLimitError("Parquet row group exceeds decode bounds")
                if group.total_byte_size > bounds.row_group_bytes:
                    raise ArtifactLimitError("Parquet row group exceeds decode bounds")
        except Exception:
            source.close()
            raise
        return source

    def verify(self, reference: ArtifactRef) -> None:
        self.store.verify_object(reference.object)
        try:
            with self._parquet(reference) as source:
                count = 0
                for batch in source.iter_batches(
                    batch_size=self.store.bounds.batch_rows, use_threads=False
                ):
                    if batch.nbytes > self.store.bounds.row_group_bytes:
                        raise ArtifactLimitError("Decoded batch exceeds bytes")
                    self.store.check()
                    for record in batch.to_pylist():
                        value_size(record, self.store.bounds)
                    count += batch.num_rows
                if count != reference.row_count:
                    raise ArtifactError("Decoded artifact row count mismatch")
        except (pa.ArrowException, OSError) as exc:
            raise ArtifactError("Unreadable Parquet artifact") from exc

    def records(self, reference: ArtifactRef) -> Iterator[dict[str, object]]:
        with self._parquet(reference) as source:
            for batch in source.iter_batches(
                batch_size=self.store.bounds.batch_rows, use_threads=False
            ):
                self.store.check()
                yield from cast(list[dict[str, object]], batch.to_pylist())
