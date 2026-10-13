"""Stream one bounded immutable object into an owned staging file."""

import hashlib
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
)


class StagedObjectWriter:
    """Write and verify bytes before the store admits their final identity."""

    def __init__(
        self, root: Path, bounds: ArtifactBounds, check: Callable[[], None]
    ) -> None:
        self.root = root
        self.bounds = bounds
        self.check = check

    @contextmanager
    def stage(
        self, chunks: Iterable[bytes], expected: StoredObject | None
    ) -> Iterator[tuple[Path, StoredObject]]:
        """Close staged bytes before admission and remove them on every exit."""
        target = tempfile.NamedTemporaryFile(
            dir=self.root, prefix=".staging-", delete=False
        )
        temporary = Path(target.name)
        try:
            with target:
                reference = self._write_chunks(target.file, chunks, expected)
            yield temporary, reference
        finally:
            temporary.unlink(missing_ok=True)

    def _write_chunks(
        self,
        target: IO[bytes],
        chunks: Iterable[bytes],
        expected: StoredObject | None,
    ) -> StoredObject:
        """Enforce per-file and exact-reference bounds while hashing the stream."""
        digest = hashlib.sha256()
        bytes_written = 0
        for chunk in chunks:
            self.check()
            if not isinstance(chunk, bytes):
                raise ArtifactError("Object chunks must be bytes")
            bytes_written += len(chunk)
            if bytes_written > self.bounds.file_bytes:
                raise ArtifactLimitError("Exceeded file bytes")
            if expected is not None and bytes_written > expected.byte_count:
                raise ArtifactError("Object differs from expected exact identity")
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
        return reference
