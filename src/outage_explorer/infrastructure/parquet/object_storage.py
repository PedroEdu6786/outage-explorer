"""Content-addressed local files, staging capacity, and atomic installation."""

import hashlib
import os
import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from threading import RLock

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.infrastructure.parquet.staged_object import StagedObjectWriter


class LocalObjectStore:
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
        self._writer = StagedObjectWriter(root, bounds, lambda: self.check())

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
        """Stream, verify, and atomically admit one immutable object."""
        if expected is not None:
            self._path(expected)
        try:
            with self._writer.stage(chunks, expected) as (temporary, reference):
                self._commit_staged_file(temporary, reference)
                return reference
        except OSError as exc:
            raise ArtifactError("Cannot persist immutable object") from exc

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
