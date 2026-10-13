"""Fail-closed cleanup of disposable cache files after worker reconciliation."""

import os
import re
import shutil
import stat
from pathlib import Path


def reclaim_private_cache(root: Path, *, file_limit: int) -> None:
    """Reclaim only known paths after exclusive analytical ownership is established."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Private modeled cache unavailable")
    paths: list[Path] = []
    for path in root.iterdir():
        if len(paths) >= file_limit:
            raise ValueError("Private cache recovery limit exceeded")
        info = path.lstat()
        if info.st_uid != os.getuid() or path.is_symlink():
            raise ValueError("Invalid disposable cache file")
        if stat.S_ISREG(info.st_mode) and re.fullmatch(
            r"[0-9a-f]{64}-(national|facilities|generators)\.parquet", path.name
        ):
            paths.append(path)
        elif stat.S_ISDIR(info.st_mode) and path.name.startswith(".preparing-"):
            paths.append(path)
        else:
            raise ValueError("Unknown private cache path")
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
