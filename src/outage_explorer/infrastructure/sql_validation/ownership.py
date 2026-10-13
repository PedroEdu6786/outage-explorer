"""Persistent parser admission lease retained by both parent and child descriptors."""

import fcntl
import os
import stat
from pathlib import Path

from outage_explorer.application.errors import RuntimeUnavailableError


def _descend_directory(parent_fd: int, component: str) -> int:
    """Open a child without following links, then release its parent handle."""
    child_fd = os.open(
        component,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    os.close(parent_fd)
    return child_fd


def _create_private_leaf(parent_fd: int, name: str) -> None:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        # The existing entry is opened without following links and checked below.
        pass


def _open_private_root(root: Path) -> int:
    components = root.parts[1:]
    current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in components[:-1]:
            current_fd = _descend_directory(current_fd, component)
        if components:
            leaf = components[-1]
            _create_private_leaf(current_fd, leaf)
            current_fd = _descend_directory(current_fd, leaf)

        info = os.fstat(current_fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise OSError
        return current_fd
    except BaseException:
        # A successful return transfers the descriptor to the caller.
        os.close(current_fd)
        raise


def _acquire_lock(directory_fd: int) -> int:
    fd = os.open(
        "parser.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise OSError
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


class ParserOwnership:
    def __init__(self, root: Path) -> None:
        if (
            not root.is_absolute()
            or ".." in root.parts
            or str(root) != str(root.absolute())
        ):
            raise ValueError("Private absolute parser ownership root required")
        self.root = root
        self.fd: int | None = None

    def open(self) -> None:
        if self.fd is not None:
            return
        try:
            directory_fd = _open_private_root(self.root)
            try:
                self.fd = _acquire_lock(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            raise RuntimeUnavailableError("Parser ownership unavailable") from None

    def close(self) -> None:
        if self.fd is not None:
            # Do not LOCK_UN: the inherited child descriptor must retain the lease
            # if the parent dies. Never unlink/replace this stable lock inode.
            os.close(self.fd)
            self.fd = None
