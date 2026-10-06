"""Strong recovery leases and a bounded, locked private creation ledger."""

import fcntl
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.application.ports.execution import RecoveryLease


class RecoveryOwner:
    def __init__(self) -> None:
        self._leases: list[tuple[Callable[[], None], tuple[RecoveryLease, ...]]] = []
        self._lock = RLock()

    def retain(
        self, reap: Callable[[], None], leases: tuple[RecoveryLease, ...]
    ) -> None:
        with self._lock:
            self._leases.append((reap, leases))

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._leases)

    def reconcile(self) -> None:
        with self._lock:
            for reap, leases in tuple(self._leases):
                try:
                    reap()
                    for lease in leases:
                        lease.close()
                except Exception:
                    continue
                self._leases.remove((reap, leases))


class OwnershipLedger:
    """One unresolved worker per owner. Explicit open, never import-time I/O."""

    def __init__(self, root: Path, owner: str) -> None:
        if re.fullmatch(r"[0-9a-f]{32}", owner) is None:
            raise ValueError("Invalid runtime owner")
        self.root, self.owner = root, owner
        self._fd: int | None = None

    def open(self) -> None:
        if self._fd is not None:
            return
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (
            self.root.is_symlink()
            or self.root.stat().st_uid != os.getuid()
            or self.root.stat().st_mode & 0o077
        ):
            raise RuntimeUnavailableError("Private runtime ownership unavailable")
        fd = os.open(
            self.root / "owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                raise OSError("Invalid owner lock")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise RuntimeUnavailableError("Runtime ownership busy") from None
        self._fd = fd

    def read(self) -> dict[str, str] | None:
        if self._fd is None:
            raise RuntimeUnavailableError("Runtime ownership unstarted")
        path = self.root / "worker.json"
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                raise RuntimeUnavailableError("Invalid runtime ownership")
            raw = stream.read(8193)
        try:
            value = json.loads(raw)
            if (
                len(raw) > 8192
                or not isinstance(value, dict)
                or set(value) != {"owner", "name", "staging"}
                or any(not isinstance(v, str) for v in value.values())
                or re.fullmatch(r"[0-9a-f]{32}", value["owner"]) is None
                or value["name"] != "outage-analytical-" + value["owner"]
            ):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise RuntimeUnavailableError("Invalid runtime ownership") from None

    def intend(self, staging: str) -> None:
        if self.read() is not None:
            raise RuntimeUnavailableError("Unresolved runtime ownership")
        value = {
            "owner": self.owner,
            "name": "outage-analytical-" + self.owner,
            "staging": staging,
        }
        raw = json.dumps(value, separators=(",", ":")).encode()
        if len(raw) > 8192:
            raise RuntimeUnavailableError("Runtime ownership limit exceeded")
        temporary = self.root / "worker.partial"
        fd = os.open(
            temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.root / "worker.json")
        self._sync()

    def clear(self) -> None:
        if self._fd is None:
            raise RuntimeUnavailableError("Runtime ownership unstarted")
        (self.root / "worker.json").unlink(missing_ok=True)
        self._sync()

    def _sync(self) -> None:
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
