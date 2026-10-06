"""Private spill on an externally provisioned finite ext4 filesystem.

The kernel, not this adapter, enforces blocks/inodes. No mount, resize, privileged
helper or cooperative file-size accounting is performed by the application.
"""

import fcntl
import json
import os
import platform
import re
import shutil
import socket
import stat
from pathlib import Path

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile


def validate_native_daemon(profile: RuntimeProfile, raw: bytes) -> None:
    try:
        value = json.loads(raw)
        endpoint = Path(profile.daemon_endpoint.removeprefix("unix://"))
        info = endpoint.stat()
        architecture = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
        if (
            platform.system() != "Linux"
            or str(endpoint.resolve()) != "/run/docker.sock"
            or not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != 0
            or value
            != {
                "version": profile.daemon_version,
                "os": "linux",
                "kernel": platform.release(),
                "name": socket.gethostname(),
                "architecture": platform.machine(),
            }
            or profile.platform != "linux/" + architecture
        ):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeUnavailableError("Native analytical daemon unavailable") from None


def _open_directory(path: Path) -> int:
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _mount(root: Path) -> tuple[str, ...]:
    # Bounded namespace description, never shell output or application secrets.
    with Path("/proc/self/mountinfo").open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError()
    matches = []
    for line in raw.decode("ascii").splitlines():
        before, after = line.split(" - ", 1)
        fields, filesystem = before.split(), after.split()
        mountpoint = fields[4]
        # Escaped paths are intentionally unsupported; config forbids separators.
        if "\\" in mountpoint:
            continue
        if root in Path(mountpoint).parents:
            raise ValueError("Nested spill mount")
        if mountpoint == str(root):
            options = set(fields[5].split(","))
            if (
                fields[3] != "/"
                or filesystem[0] != "ext4"
                or not filesystem[1].startswith("/dev/")
                or not {"rw", "noexec", "nosuid", "nodev"} <= options
                or "ro" in options
                or "rw" not in filesystem[2].split(",")
            ):
                raise ValueError("Unsupported spill filesystem")
            matches.append((fields[0], fields[2], filesystem[1]))
    if len(matches) != 1:
        raise ValueError("Dedicated spill mount required")
    return matches[0]


class DiskSpill:
    """One filesystem admission lock, held through confirmed worker removal."""

    def __init__(self, profile: RuntimeProfile, owner: str) -> None:
        if re.fullmatch(r"[0-9a-f]{32}", owner) is None:
            raise ValueError("Invalid spill owner")
        self.profile = profile
        self.root = Path(profile.temporary_root)
        self.directory = self.root / ("execution-" + owner)
        self._root_fd: int | None = None
        self._lock_fd: int | None = None
        self._identity: tuple[int, int] | None = None
        self._directory_identity: tuple[int, int] | None = None
        self._mount_identity: tuple[str, ...] | None = None
        self._capacity_identity: tuple[int, int, int] | None = None

    def validate(self) -> None:
        try:
            self._validate()
        except (OSError, ValueError):
            raise RuntimeUnavailableError(
                "Analytical spill filesystem unavailable"
            ) from None

    def _validate(self) -> None:
        p = self.profile
        if (
            platform.system() != "Linux"
            or p.temporary_backend != "quota-disk"
            or os.getuid() != p.uid
            or os.getgid() != p.gid
            or any(c in str(self.root) for c in (",", "\\", " ", "\n", "\t"))
        ):
            raise RuntimeUnavailableError("Analytical spill host unavailable")
        fd = _open_directory(self.root)
        try:
            info, capacity = os.fstat(fd), os.fstatvfs(fd)
            mount_identity = _mount(self.root)
            identity = (info.st_dev, info.st_ino)
            filesystem_identity = (
                f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}:{capacity.f_fsid}"
            )
            capacity_identity = (capacity.f_blocks, capacity.f_frsize, capacity.f_files)
            if (
                info.st_uid != p.uid
                or info.st_gid != p.gid
                or stat.S_IMODE(info.st_mode) != 0o700
                or filesystem_identity != p.temporary_filesystem_identity
                or not 0
                < capacity.f_blocks * capacity.f_frsize
                <= p.worker.temporary_bytes
                or not 0 < capacity.f_files <= p.temporary_inodes
                or capacity.f_flag & os.ST_RDONLY
                or self._identity is not None
                and identity != self._identity
                or self._mount_identity is not None
                and mount_identity != self._mount_identity
                or self._capacity_identity is not None
                and capacity_identity != self._capacity_identity
            ):
                raise ValueError()
            self._identity, self._mount_identity = identity, mount_identity
            self._capacity_identity = capacity_identity
        finally:
            os.close(fd)

    def open(self, *, recovering: bool = False) -> None:
        if self._root_fd is not None:
            self.validate()
            return
        try:
            self.validate()
            self._root_fd = _open_directory(self.root)
            self._lock_fd = os.open(
                ".quota.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
                dir_fd=self._root_fd,
            )
            info = os.fstat(self._lock_fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.profile.uid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise ValueError()
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.validate()
            allowed = {".quota.lock"}
            if recovering:
                allowed.add(self.directory.name)
            if not set(os.listdir(self._root_fd)) <= allowed:
                raise ValueError("Unresolved spill ownership")
            if recovering and self.directory.exists():
                self._check_directory()
        except (OSError, ValueError, RuntimeUnavailableError):
            self.release()
            raise RuntimeUnavailableError(
                "Private analytical spill unavailable"
            ) from None

    def allocate(self) -> None:
        if self._root_fd is None:
            raise RuntimeUnavailableError("Analytical spill unstarted")
        self.validate()
        os.mkdir(self.directory.name, 0o700, dir_fd=self._root_fd)
        os.fsync(self._root_fd)
        self._check_directory()

    def _check_directory(self) -> None:
        info = self.directory.lstat()
        identity = (info.st_dev, info.st_ino)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != self.profile.uid
            or info.st_gid != self.profile.gid
            or self._identity is None
            or info.st_dev != self._identity[0]
            or self._directory_identity is not None
            and identity != self._directory_identity
        ):
            raise RuntimeUnavailableError("Analytical spill identity changed")
        self._directory_identity = identity

    def mount_argument(self) -> str:
        self.validate()
        self._check_directory()
        return f"type=bind,src={self.directory},dst=/tmp,bind-recursive=disabled"

    def close(self) -> None:
        # Caller proves complete worker removal first. On any cleanup failure
        # retain the lock/descriptors and directory for supervisor retry.
        self.validate()
        if self.directory.exists() or self.directory.is_symlink():
            self._check_directory()
            # Same non-root UID can reclaim restrictive worker directory modes.
            os.chmod(self.directory, 0o700, follow_symlinks=False)
            for directory, children, _ in os.walk(self.directory, followlinks=False):
                os.chmod(directory, 0o700, follow_symlinks=False)
                for child in children:
                    path = Path(directory) / child
                    if stat.S_ISDIR(path.lstat().st_mode):
                        os.chmod(path, 0o700, follow_symlinks=False)
            shutil.rmtree(self.directory)
            assert self._root_fd is not None
            os.fsync(self._root_fd)

    def release(self) -> None:
        for attribute in ("_lock_fd", "_root_fd"):
            fd = getattr(self, attribute)
            if fd is not None:
                os.close(fd)
                setattr(self, attribute, None)
