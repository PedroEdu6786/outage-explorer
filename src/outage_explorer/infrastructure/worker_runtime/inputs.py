"""Private copies of approved inputs; no directory binds or mutable hardlinks."""

import hashlib
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from time import monotonic

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile


class StagedInputs:
    def __init__(self, directory: Path, files: tuple[ApprovedFile, ...]) -> None:
        self.directory, self.files = directory, files
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            shutil.rmtree(self.directory)
            self._closed = True


def _open_regular(path: Path) -> int:
    # Traverse every component with directory descriptors; O_NOFOLLOW on the
    # final component alone would still accept symlinked parent directories.
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Absolute input path required")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            os.close(parent)
            parent = child
        return os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
    finally:
        os.close(parent)


def stage_inputs(
    profile: RuntimeProfile, files: tuple[ApprovedFile, ...], deadline: float
) -> StagedInputs:
    unique: dict[str, ApprovedFile] = {}
    for item in files:
        if (
            re.fullmatch(r"[0-9a-f]{64}", item.sha256) is None
            or type(item.byte_count) is not int
            or item.byte_count <= 0
            or type(item.rows) is not int
            or item.rows <= 0
        ):
            raise DataUnavailableError("Invalid approved input")
        previous = unique.get(item.sha256)
        if previous is not None and previous != item:
            raise DataUnavailableError("Conflicting approved input")
        unique[item.sha256] = item
    if len(unique) > profile.input_files or sum(
        f.byte_count for f in unique.values()
    ) > min(profile.input_bytes, profile.staging_bytes):
        raise AnalyticalResourceError("Analytical input limit exceeded")
    root = Path(profile.staging_root)
    # Root creation/ownership belongs to explicit startup, never this builder.
    if (
        root.is_symlink()
        or not root.is_dir()
        or root.stat().st_uid != os.getuid()
        or stat.S_IMODE(root.stat().st_mode) != 0o700
    ):
        raise DataUnavailableError("Private analytical staging unavailable")
    directory = Path(tempfile.mkdtemp(prefix="execution-", dir=root))
    result = StagedInputs(directory, ())
    staged = []

    def check() -> None:
        if monotonic() >= deadline:
            raise AnalyticalResourceError("Analytical preparation deadline exceeded")

    try:
        for item in unique.values():
            check()
            source_fd = _open_regular(Path(item.path))
            with os.fdopen(source_fd, "rb") as source:
                before = os.fstat(source.fileno())
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_size != item.byte_count
                ):
                    raise ValueError("Input identity mismatch")
                partial = directory / (item.sha256 + ".partial")
                digest = hashlib.sha256()
                size = 0
                with partial.open("xb") as target:
                    while chunk := source.read(65536):
                        check()
                        size += len(chunk)
                        if size > item.byte_count:
                            raise ValueError("Input grew")
                        digest.update(chunk)
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                after = os.fstat(source.fileno())
                # Reopen through trusted traversal and compare identity after copy.
                current_fd = _open_regular(Path(item.path))
                try:
                    current = os.fstat(current_fd)
                finally:
                    os.close(current_fd)

                def identity(s: os.stat_result) -> tuple[int, int, int, int, int]:
                    return (
                        s.st_dev,
                        s.st_ino,
                        s.st_size,
                        s.st_mtime_ns,
                        s.st_ctime_ns,
                    )

                if (
                    identity(before) != identity(after)
                    or identity(after) != identity(current)
                    or size != item.byte_count
                    or digest.hexdigest() != item.sha256
                ):
                    raise ValueError("Input changed")
                check()
                if pq.ParquetFile(partial).metadata.num_rows != item.rows:
                    raise ValueError("Input row identity mismatch")
                check()
                final = directory / (item.sha256 + ".parquet")
                os.chmod(partial, 0o444)
                os.replace(partial, final)
                staged.append(
                    ApprovedFile(str(final), item.sha256, item.byte_count, item.rows)
                )
        result.files = tuple(staged)
        return result
    except AnalyticalResourceError:
        result.close()
        raise
    except Exception:
        result.close()
        raise DataUnavailableError("Approved analytical input unavailable") from None
    except BaseException:
        result.close()
        raise
