"""Process-owned private immutable spools; no unexpired eviction or durable state."""

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import RLock
from typing import BinaryIO
from uuid import uuid4

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    QueryExpiredError,
    QueryPageError,
    QueryUnavailableError,
    ResultCapacityError,
)
from outage_explorer.application.ports.clock import Clock
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.query_results import (
    LIFETIME_SECONDS,
    MAX_BYTES,
    MAX_ROWS,
    ResultIdentity,
    validate_page,
)
from outage_explorer.infrastructure.query_results.encoding import canonical_json


@dataclass(frozen=True)
class ResultBounds:
    per_user: int
    global_count: int
    total_bytes: int
    metadata_bytes: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("Positive explicit result bounds required")
        if self.per_user > self.global_count or self.metadata_bytes < 32_000:
            raise ValueError("Incompatible result bounds")

    @property
    def reservation_bytes(self) -> int:
        return MAX_BYTES + self.metadata_bytes


@dataclass
class _Record:
    identity: ResultIdentity
    path: Path
    digest: str
    size: int
    offsets: tuple[tuple[int, int], ...]
    metadata: dict[str, object]
    readers: int = 0


class BoundedQueryResults:
    def __init__(self, root: Path, clock: Clock, bounds: ResultBounds) -> None:
        # Construction is inert. Explicit startup owns all filesystem resources.
        self._root, self._clock, self._bounds = root, clock, bounds
        self._pid = os.getpid()
        self._lock = RLock()
        self._directory: Path | None = None
        self._owner_lock: BinaryIO | None = None
        self._records: dict[str, _Record] = {}
        self._pending: dict[str, str] = {}
        self._closed = False

    def start(self, *, serving_processes: int = 1) -> None:
        with self._lock:
            if serving_processes != 1 or os.getpid() != self._pid:
                raise ValueError("Ephemeral query ownership requires one process")
            if self._closed:
                raise ValueError("Result store already closed")
            if self._directory is not None:
                return
            if self._root.is_symlink():
                raise ValueError("Private spool root must not be a symlink")
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._directory = self._root / f"owner-{uuid4().hex}"
            self._directory.mkdir(mode=0o700)
            self._owner_lock = (self._directory / "owner.lock").open("xb+")
            fcntl.flock(self._owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _check(self) -> Path:
        if os.getpid() != self._pid or self._closed or self._directory is None:
            raise QueryUnavailableError("Result store unavailable")
        return self._directory

    def reserve(self, owner: str) -> "_Reservation":
        with self._lock:
            self._check()
            if not owner or len(owner) > 256:
                raise ValueError("Bounded local owner identity required")
            owners = [record.identity.owner for record in self._records.values()]
            owners.extend(self._pending.values())
            if owners.count(owner) >= self._bounds.per_user:
                raise ResultCapacityError(per_user=True)
            if (
                len(owners) >= self._bounds.global_count
                or (len(owners) + 1) * self._bounds.reservation_bytes
                > self._bounds.total_bytes
            ):
                raise ResultCapacityError(per_user=False)
            key = uuid4().hex
            self._pending[key] = owner
            return _Reservation(self, key)

    def _complete(
        self,
        key: str,
        output: QueryOutput,
        grains: frozenset[AnalyticalGrain],
        generation_id: str | None,
        page_size: int,
    ) -> ResultIdentity:
        validate_page(1, page_size)
        with self._lock:
            directory = self._check()
            owner = self._pending.get(key)
            if owner is None:
                raise QueryUnavailableError("Result reservation unavailable")
            if generation_id is not None and len(generation_id) > 256:
                raise AnalyticalResourceError("Invalid generation identity")
            metadata, offsets = _verify_output(output)
            if (
                len(canonical_json(metadata)) + len(offsets) * 24 + 1024
                > self._bounds.metadata_bytes
            ):
                raise AnalyticalResourceError("Retained metadata budget exhausted")
            completed = self._clock.now()
            identity = ResultIdentity(
                key,
                owner,
                grains,
                generation_id,
                page_size,
                completed,
                completed + timedelta(seconds=LIFETIME_SECONDS),
                output.retained_row_count,
                output.truncation_reason,
            )
            path = directory / f"{key}.json"
            try:
                with path.open("xb") as stream:
                    os.chmod(path, 0o600)
                    stream.write(output.document)
                self._records[key] = _Record(
                    identity,
                    path,
                    hashlib.sha256(output.document).hexdigest(),
                    len(output.document),
                    offsets,
                    metadata,
                )
                del self._pending[key]
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            return identity

    def acquire(self, query_id: str, owner: str) -> "_Reader":
        with self._lock:
            self._check()
            record = self._records.get(query_id)
            if record is None or record.identity.owner != owner:
                raise QueryUnavailableError("Query results unavailable")
            if self._clock.now() >= record.identity.expires_at:
                raise QueryExpiredError("Query results expired")
            record.readers += 1
            return _Reader(self, record)

    def cleanup(self) -> int:
        with self._lock:
            self._check()
            removed = 0
            for key, record in tuple(self._records.items()):
                if (
                    not record.readers
                    and self._clock.now() >= record.identity.expires_at
                ):
                    record.path.unlink(missing_ok=True)
                    del self._records[key]
                    removed += 1
            # Advisory lock ownership proves process death, not PID reuse or age.
            for directory in self._root.glob("owner-*"):
                if (
                    directory == self._directory
                    or directory.is_symlink()
                    or not directory.is_dir()
                ):
                    continue
                lock = directory / "owner.lock"
                if lock.is_symlink() or not lock.is_file():
                    continue
                with lock.open("rb") as stream:
                    try:
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    for path in directory.glob("*.json"):
                        if (
                            not path.is_symlink()
                            and len(path.stem) == 32
                            and all(c in "0123456789abcdef" for c in path.stem)
                        ):
                            path.unlink()
                            removed += 1
                    # Preserve unknown/durable files even in a dead owner directory.
                    if set(directory.iterdir()) == {lock}:
                        lock.unlink()
                        directory.rmdir()
            return removed

    def close(self) -> None:
        with self._lock:
            if os.getpid() != self._pid:
                raise ValueError("Store ownership changed")
            if any(record.readers for record in self._records.values()):
                raise ValueError("Active result readers must finish before shutdown")
            if self._pending:
                raise ValueError("In-flight reservations must finish before shutdown")
            for record in self._records.values():
                record.path.unlink(missing_ok=True)
            self._records.clear()
            if self._owner_lock is not None:
                self._owner_lock.close()
                self._owner_lock = None
            if self._directory is not None:
                (self._directory / "owner.lock").unlink(missing_ok=True)
                self._directory.rmdir()
                self._directory = None
            self._closed = True


def _verify_output(
    output: QueryOutput,
) -> tuple[dict[str, object], tuple[tuple[int, int], ...]]:
    if type(output.document) is not bytes or len(output.document) > MAX_BYTES:
        raise AnalyticalResourceError("Invalid retained output size")
    try:
        document = json.loads(output.document)
        if not isinstance(document, dict) or set(document) != {
            "encoding_version",
            "columns",
            "rows",
            "retained_row_count",
            "truncated",
            "truncation_reason",
            "limits",
        }:
            raise ValueError
        rows = document["rows"]
        columns = document["columns"]
        if (
            document["encoding_version"] != "1"
            or not isinstance(columns, list)
            or not isinstance(rows, list)
            or not 0 <= len(rows) <= MAX_ROWS
            or type(output.retained_row_count) is not int
            or len(rows) != output.retained_row_count
            or document["retained_row_count"] != len(rows)
            or document["truncation_reason"] != output.truncation_reason
            or output.truncation_reason not in (None, "row_limit", "byte_limit")
            or document["truncated"] is not (output.truncation_reason is not None)
            or document["limits"] != {"max_rows": MAX_ROWS, "max_bytes": MAX_BYTES}
            or canonical_json(document) != output.document
            or any(
                not isinstance(row, list) or len(row) != len(columns) for row in rows
            )
        ):
            raise ValueError
        cursor = output.document.index(b',"rows":[') + len(b',"rows":[')
        offsets = []
        for row in rows:
            size = len(canonical_json(row))
            offsets.append((cursor, size))
            cursor += size + 1
        metadata = {key: value for key, value in document.items() if key != "rows"}
        return metadata, tuple(offsets)
    except (ValueError, TypeError, UnicodeError, KeyError) as exc:
        raise AnalyticalResourceError("Invalid canonical retained output") from exc


class _Reservation:
    def __init__(self, store: BoundedQueryResults, key: str) -> None:
        self._store, self._key = store, key

    def complete(
        self,
        output: QueryOutput,
        grains: frozenset[AnalyticalGrain],
        generation_id: str | None,
        page_size: int,
    ) -> ResultIdentity:
        return self._store._complete(
            self._key, output, grains, generation_id, page_size
        )

    def close(self) -> None:
        with self._store._lock:
            self._store._pending.pop(self._key, None)


class _Reader:
    def __init__(self, store: BoundedQueryResults, record: _Record) -> None:
        self._store, self._record = store, record
        self._closed = False

    @property
    def identity(self) -> ResultIdentity:
        return self._record.identity

    def page(self, page: int) -> dict[str, object]:
        if self._closed:
            raise QueryUnavailableError("Result reader closed")
        try:
            start, end = self.identity.position(page)
        except ValueError as exc:
            raise QueryPageError("page_out_of_range", self.identity) from exc
        path = self._record.path
        try:
            if path.is_symlink() or path.stat().st_size != self._record.size:
                raise ValueError
            with path.open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
                if hashlib.sha256(data).hexdigest() != self._record.digest:
                    raise ValueError
                rows: list[object] = []
                for offset, size in self._record.offsets[start:end]:
                    stream.seek(offset)
                    rows.append(json.loads(stream.read(size)))
        except (OSError, ValueError) as exc:
            raise QueryUnavailableError("Query results unavailable") from exc
        return {
            **self._record.metadata,
            "rows": rows,
            "query_id": self.identity.id,
            "generation_id": self.identity.generation_id,
            "page": page,
            "page_size": self.identity.page_size,
            "total_pages": self.identity.total_pages,
            "has_more": page < self.identity.total_pages,
            "expires_at": self.identity.expires_at.isoformat().replace("+00:00", "Z"),
        }

    def close(self) -> None:
        with self._store._lock:
            if not self._closed:
                self._record.readers -= 1
                self._closed = True
