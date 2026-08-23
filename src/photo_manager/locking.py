"""Advisory archive locks; only destination management files are ever opened."""
from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from .runtime import RunResources, UsageError


@dataclass
class ArchiveLock:
    path: Path
    fd: int

    def release(self) -> None:
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


def _open_lock_file(directory: Path, path: Path, *, exclusive: bool) -> int:
    """Open the permanent lock file, tolerating a read-only archive mount.

    A writer must be able to create the lock, so an exclusive request keeps
    the original failure.  A shared reader on a read-only mount cannot create
    or open it read-write, yet ``flock`` needs only an open descriptor: an
    ``O_RDONLY`` handle on the *existing* lock is a real shared lock.  A
    missing lock file stays an error, because verification must never proceed
    unlocked.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        if exclusive:
            raise
        try:
            return os.open(str(path), os.O_RDONLY)
        except OSError:
            raise exc


def acquire_lock(destination: Path, *, exclusive: bool, resources: RunResources) -> ArchiveLock:
    directory = destination / "_photo-manager"
    path = directory / "import.lock"
    fd = -1
    try:
        fd = _open_lock_file(directory, path, exclusive=exclusive)
        mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        fcntl.flock(fd, mode)
    except OSError as exc:
        if fd >= 0:
            os.close(fd)
        raise UsageError("archive is busy or cannot be locked: {0}".format(exc))
    lock = ArchiveLock(path, fd)
    resources.add_cleanup(lock.release)
    return lock


def acquire_mirror_locks(volumes: Sequence[Tuple[str, Path]], resources: RunResources) -> List[ArchiveLock]:
    """Acquire exclusive locks in UUID order to prevent lock-order deadlocks."""
    if len(volumes) != 2:
        raise ValueError("mirror requires exactly two volumes")
    if volumes[0][0].casefold() == volumes[1][0].casefold():
        raise UsageError("mirror source and destination must be different volumes")
    locks = []
    for _uuid, path in sorted(volumes, key=lambda item: item[0].casefold()):
        locks.append(acquire_lock(path, exclusive=True, resources=resources))
    return locks
