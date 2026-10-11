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
        self._transient_bytes = 0
        self._objects: set[str] = set()
        root.mkdir(parents=True, exist_ok=True)

    def contains(self, reference: StoredObject) -> bool:
        """Check for a local file; callers must verify it before reuse."""
        return self._path(reference).exists()

    def check_recovery_capacity(self, missing: tuple[ArtifactRef, ...]) -> None:
        """Preflight missing files; writes still enforce capacity under the lock."""
        download_bytes = sum(reference.object.byte_count for reference in missing)
        with self._lock:
            total_file_count = len(self._objects) + len(missing)
            if total_file_count > self.bounds.objects:
                raise ArtifactLimitError(
                    "Resource recovery exceeds aggregate staging bounds"
                )

            occupied_bytes = self._bytes + self._transient_bytes
            total_bytes_after_download = occupied_bytes + download_bytes
            if total_bytes_after_download > self.bounds.total_bytes:
                raise ArtifactLimitError(
                    "Resource recovery exceeds aggregate staging bounds"
                )

    def account_transient(self, size: int) -> None:
        """Charge cumulative transient input against this shared staging session.

        Accounting remains conservative after inputs are released, just as
        immutable file writes consume the session's aggregate budget.
        """
        self.check()
        with self._lock:
            occupied_bytes = self._bytes + self._transient_bytes
            if occupied_bytes + size > self.bounds.total_bytes:
                raise ArtifactLimitError("Exceeded aggregate transient staging bytes")
            self._transient_bytes += size

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

    def discard_owned(self, reference: StoredObject) -> None:
        """Remove an explicitly tracked recovery-owned file after workers join."""
        path = self._path(reference, check=False)
        with self._lock:
            path.unlink(missing_ok=True)
            if reference.key in self._objects:
                self._objects.remove(reference.key)
                self._bytes -= reference.byte_count

    def _path(self, reference: StoredObject, *, check: bool = True) -> Path:
        if check:
            self.check()
        if not re.fullmatch(r"[0-9a-f]{64}", reference.key):
            raise ArtifactError("Invalid immutable object identity")
        if reference.sha256 != reference.key:
            raise ArtifactError("Invalid immutable object identity")
        if type(reference.byte_count) is not int:
            raise ArtifactLimitError("Invalid or oversized object bytes")
        if not 0 < reference.byte_count <= self.bounds.file_bytes:
            raise ArtifactLimitError("Invalid or oversized object bytes")
        path = self.root / reference.key
        if path.is_symlink():
            raise ArtifactError("Object must not be a symbolic link")
        return path

    def put_immutable(
        self, chunks: Iterable[bytes], *, expected: StoredObject | None = None
    ) -> StoredObject:
        if expected is not None:
            self._path(expected)
        temporary: Path | None = None
        try:
            digest = hashlib.sha256()
            bytes_written = 0
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix=".staging-", delete=False
            ) as target:
                temporary = Path(target.name)
                for chunk in chunks:
                    self.check()
                    if not isinstance(chunk, bytes):
                        raise ArtifactError("Object chunks must be bytes")
                    bytes_written += len(chunk)
                    if bytes_written > self.bounds.file_bytes:
                        raise ArtifactLimitError("Exceeded file bytes")
                    if expected is not None and bytes_written > expected.byte_count:
                        raise ArtifactError(
                            "Object differs from expected exact identity"
                        )
                    target.write(chunk)
                    digest.update(chunk)
                self.check()
                if not bytes_written:
                    raise ArtifactError("Empty object")
                checksum = digest.hexdigest()
                reference = StoredObject(checksum, checksum, bytes_written)
                if expected is not None and reference != expected:
                    raise ArtifactError("Object differs from expected exact identity")
                target.flush()
                os.fsync(target.fileno())
            self._commit_staged_file(temporary, reference)
            return reference
        except OSError as exc:
            raise ArtifactError("Cannot persist immutable object") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _commit_staged_file(self, temporary: Path, reference: StoredObject) -> None:
        """Install verified bytes atomically and count each identity once."""
        path = self._path(reference)
        # Downloads stay outside this lock so independent transfers can proceed.
        with self._lock:
            if reference.key in self._objects:
                self.verify_object(reference)
                return

            if len(self._objects) >= self.bounds.objects:
                raise ArtifactLimitError("Exceeded object count")
            occupied_bytes = self._bytes + self._transient_bytes
            if occupied_bytes + reference.byte_count > self.bounds.total_bytes:
                raise ArtifactLimitError("Exceeded total bytes")

            try:
                os.link(temporary, path)
            except FileExistsError:
                self.verify_object(reference)
            self._objects.add(reference.key)
            self._bytes += reference.byte_count

    def verify_object(self, reference: StoredObject) -> None:
        path = self._path(reference)
        try:
            if path.stat().st_size != reference.byte_count:
                raise ArtifactError("Object byte count mismatch")
            digest = hashlib.sha256()
            bytes_read = 0
            with path.open("rb") as source:
                while chunk := source.read(min(65536, self.bounds.file_bytes)):
                    self.check()
                    bytes_read += len(chunk)
                    if bytes_read > reference.byte_count:
                        raise ArtifactError("Object grew while reading")
                    digest.update(chunk)
            if bytes_read != reference.byte_count:
                raise ArtifactError("Object checksum mismatch")
            actual_checksum = digest.hexdigest()
            if actual_checksum != reference.sha256:
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
