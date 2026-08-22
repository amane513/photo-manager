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


def acquire_lock(destination: Path, *, exclusive: bool, resources: RunResources) -> ArchiveLock:
    directory = destination / "_photo-manager"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "import.lock"
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
        mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        fcntl.flock(fd, mode)
    except OSError as exc:
        try:
            os.close(fd)  # type: ignore[name-defined]
        except (UnboundLocalError, OSError):
            pass
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
