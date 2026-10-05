"""Local content-addressed storage with explicit staging and decode bounds."""

import hashlib
import io
import math
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactKind,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.infrastructure.parquet.schemas import schema_for


def value_size(value: object, bounds: ArtifactBounds, depth: int = 0) -> int:
    """Bound recursively before Arrow/JSON allocation; approximate Python payload."""
    if depth > bounds.json_depth:
        raise ArtifactLimitError("Exceeded nested value depth")
    if isinstance(value, str):
        if len(value) > bounds.field_bytes:
            raise ArtifactLimitError("Exceeded field bytes")
        size = len(value.encode("utf-8"))
        if size > bounds.field_bytes:
            raise ArtifactLimitError("Exceeded field bytes")
        return size + 8
    if value is None or isinstance(value, (bool, date, datetime, Decimal)):
        return 32
    if type(value) is int:
        if value.bit_length() > bounds.field_bytes * 3:
            raise ArtifactLimitError("Exceeded integer bytes")
        return max(8, value.bit_length())
    if type(value) is float:
        if not math.isfinite(value):
            raise ArtifactError("JSON values must be finite")
        return 16
    if isinstance(value, (dict, list, tuple)):
        count = len(value)
        if count > bounds.row_group_bytes:
            raise ArtifactLimitError("Exceeded collection size")
        size = 8
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ArtifactError("Object keys must be strings")
                size += value_size(key, bounds, depth + 1) + value_size(
                    item, bounds, depth + 1
                )
                if size > bounds.row_group_bytes:
                    raise ArtifactLimitError("Exceeded row-group bytes")
        else:
            for item in value:
                size += value_size(item, bounds, depth + 1)
                if size > bounds.row_group_bytes:
                    raise ArtifactLimitError("Exceeded row-group bytes")
        return size
    raise ArtifactError("Unsupported artifact value")


class _LimitedBuffer(io.BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: Any) -> int:
        if self.tell() + len(data) > self.limit:
            raise ArtifactLimitError("Exceeded file bytes")
        return super().write(data)


class LocalParquetStore:
    """An explicitly bounded write session; limits are not production defaults."""

    def __init__(
        self,
        root: Path,
        bounds: ArtifactBounds,
        check: Callable[[], None] | None = None,
    ) -> None:
        self.check: Callable[[], None] = (lambda: None) if check is None else check
        self.root = root
        self.bounds = bounds
        self._lock = RLock()
        self._bytes = 0
        self._objects: set[str] = set()
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, reference: StoredObject) -> Path:
        self.check()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", reference.key)
            or reference.sha256 != reference.key
        ):
            raise ArtifactError("Invalid immutable object identity")
        if (
            type(reference.byte_count) is not int
            or not 0 < reference.byte_count <= self.bounds.file_bytes
        ):
            raise ArtifactLimitError("Invalid or oversized object bytes")
        path = self.root / reference.key
        if path.is_symlink():
            raise ArtifactError("Object must not be a symbolic link")
        return path

    def put_immutable(self, chunks: Iterable[bytes]) -> StoredObject:
        data = _LimitedBuffer(self.bounds.file_bytes)
        for chunk in chunks:
            self.check()
            if not isinstance(chunk, bytes):
                raise ArtifactError("Object chunks must be bytes")
            data.write(chunk)
        payload = data.getvalue()
        if not payload:
            raise ArtifactError("Empty object")
        digest = hashlib.sha256(payload).hexdigest()
        reference = StoredObject(digest, digest, len(payload))
        path = self._path(reference)
        with self._lock:
            if digest not in self._objects:
                if len(self._objects) >= self.bounds.objects:
                    raise ArtifactLimitError("Exceeded object count")
                if self._bytes + len(payload) > self.bounds.total_bytes:
                    raise ArtifactLimitError("Exceeded total bytes")
                temporary: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=self.root, prefix=".staging-", delete=False
                    ) as target:
                        temporary = Path(target.name)
                        target.write(payload)
                        target.flush()
                        os.fsync(target.fileno())
                    try:
                        os.link(temporary, path)
                    except FileExistsError:
                        self.verify_object(reference)
                except OSError as exc:
                    raise ArtifactError("Cannot persist immutable object") from exc
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                self._objects.add(digest)
                self._bytes += len(payload)
            else:
                self.verify_object(reference)
        return reference

    def verify_object(self, reference: StoredObject) -> None:
        path = self._path(reference)
        try:
            if path.stat().st_size != reference.byte_count:
                raise ArtifactError("Object byte count mismatch")
            digest = hashlib.sha256()
            count = 0
            with path.open("rb") as source:
                while chunk := source.read(min(65536, self.bounds.file_bytes)):
                    count += len(chunk)
                    if count > reference.byte_count:
                        raise ArtifactError("Object grew while reading")
                    digest.update(chunk)
            if count != reference.byte_count or digest.hexdigest() != reference.sha256:
                raise ArtifactError("Object checksum mismatch")
        except OSError as exc:
            raise ArtifactError("Object unavailable") from exc

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        self.verify_object(reference)
        with self._path(reference).open("rb") as source:
            while chunk := source.read(min(65536, self.bounds.file_bytes)):
                self.check()
                yield chunk

    def write(
        self,
        kind: ArtifactKind,
        grain: Grain,
        partition: date | None,
        rows: Iterable[dict[str, object]],
    ) -> tuple[ArtifactRef, ...]:
        schema = schema_for(kind, grain)
        batch: list[dict[str, object]] = []
        batch_bytes = 0
        refs: list[ArtifactRef] = []
        for record in rows:
            self.check()
            size = value_size(record, self.bounds)
            if size > self.bounds.row_group_bytes:
                raise ArtifactLimitError("Exceeded row-group bytes")
            if batch and (
                len(batch) >= min(self.bounds.batch_rows, self.bounds.row_group_rows)
                or batch_bytes + size > self.bounds.row_group_bytes
            ):
                refs.append(self._write_batch(kind, grain, partition, batch, schema))
                batch, batch_bytes = [], 0
            batch.append(record)
            batch_bytes += size
        if batch:
            refs.append(self._write_batch(kind, grain, partition, batch, schema))
        return tuple(refs)

    def _write_batch(
        self,
        kind: ArtifactKind,
        grain: Grain,
        partition: date | None,
        rows: list[dict[str, object]],
        schema: Any,
    ) -> ArtifactRef:
        try:
            table = pa.Table.from_pylist(rows, schema=schema)
            if table.nbytes > self.bounds.row_group_bytes:
                raise ArtifactLimitError("Exceeded encoded row-group bytes")
            if table.to_pylist() != rows:
                raise ArtifactError("Physical conversion changed artifact values")
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

    def _parquet(self, reference: ArtifactRef) -> Any:
        if (
            reference.schema_version != "1"
            or type(reference.row_count) is not int
            or reference.row_count <= 0
        ):
            raise ArtifactError("Invalid artifact version or row count")
        source = pq.ParquetFile(
            self._path(reference.object),
            pre_buffer=False,
            page_checksum_verification=True,
            thrift_string_size_limit=self.bounds.file_bytes,
            thrift_container_size_limit=self.bounds.row_group_bytes,
        )
        try:
            if not source.schema_arrow.equals(
                schema_for(reference.kind, reference.grain), check_metadata=True
            ):
                raise ArtifactError("Physical schema mismatch")
            metadata = source.metadata
            if metadata.num_rows != reference.row_count:
                raise ArtifactError("Artifact row count mismatch")
            for index in range(metadata.num_row_groups):
                group = metadata.row_group(index)
                if (
                    group.num_rows > self.bounds.row_group_rows
                    or group.total_byte_size > self.bounds.row_group_bytes
                ):
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
