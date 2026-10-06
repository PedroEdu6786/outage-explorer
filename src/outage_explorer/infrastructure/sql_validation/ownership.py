"""Persistent parser admission lease retained by both parent and child descriptors."""

import fcntl
import os
import stat
from pathlib import Path

from outage_explorer.application.errors import RuntimeUnavailableError


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
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        fd: int | None = None
        try:
            for index, component in enumerate(self.root.parts[1:]):
                final = index == len(self.root.parts) - 2
                if final:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                child = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent,
                )
                os.close(parent)
                parent = child
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise OSError
            fd = os.open(
                "parser.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=parent,
            )
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
            ):
                raise OSError
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd = fd
            fd = None
        except OSError:
            raise RuntimeUnavailableError("Parser ownership unavailable") from None
        finally:
            os.close(parent)
            if fd is not None:
                os.close(fd)

    def close(self) -> None:
        if self.fd is not None:
            # Do not LOCK_UN: the inherited child descriptor must retain the lease
            # if the parent dies. Never unlink/replace this stable lock inode.
            os.close(self.fd)
            self.fd = None
