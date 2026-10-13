"""Immutable local object storage with a bounded Parquet interface."""

from collections.abc import Iterable, Iterator
from datetime import date

from outage_explorer.application.ports.artifacts import (
    ArtifactKind,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.infrastructure.parquet.file_io.reading import ParquetFileReader
from outage_explorer.infrastructure.parquet.file_io.writing import ParquetFileWriter
from outage_explorer.infrastructure.parquet.object_storage import LocalObjectStore
from outage_explorer.infrastructure.parquet.value_bounds import value_size as value_size


class LocalParquetStore(LocalObjectStore):
    """Expose bounded Parquet files over one immutable staging session."""

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
        return ParquetFileWriter(self).write(kind, grain, partition, rows)

    def write_file(
        self, kind: ArtifactKind, grain: Grain, rows: Iterable[dict[str, object]]
    ) -> ArtifactRef:
        """Write one bounded file; callers determine row order."""
        return ParquetFileWriter(self).write_file(kind, grain, rows)

    def verify(self, reference: ArtifactRef | StoredObject) -> None:
        if isinstance(reference, StoredObject):
            self.verify_object(reference)
            return
        ParquetFileReader(self).verify(reference)

    def records(self, reference: ArtifactRef) -> Iterator[dict[str, object]]:
        # Full verification precedes the first yield, including truncated consumers.
        self.verify(reference)
        yield from ParquetFileReader(self).records(reference)
