"""Safe, verified, destination-only file transfer primitives.

Nothing in this module opens a source for writing, unlinks a source, or
renames a source.  The only unlink operation is for a ``.part`` file created
by this invocation in the archive's private management directory.
"""
from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import re
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from .naming import PlannedAction, TransferPlan
from .runtime import OperationalError, RunResources


DEFAULT_CHUNK_SIZE = 1024 * 1024
_PART_NAME = re.compile(r"^\d{8}_\d{6}_.+\.part$")


class TransferStatus(str, Enum):
    COPIED = "copied"
    FAILED = "failed"
    CONFLICT = "conflict"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TransferResult:
    """The outcome of one transfer without conflating a race with failure.

    A ``CONFLICT`` outcome means no destination was replaced; the caller must
    re-run duplicate/numbering planning before deciding what to do next.
    """

    status: TransferStatus
    source: Path
    destination: Path
    digest: Optional[str] = None
    message: Optional[str] = None

    @property
    def needs_replan(self) -> bool:
        return self.status is TransferStatus.CONFLICT


def management_tmp_dir(destination_root: Path) -> Path:
    return destination_root / "_photo-manager" / "tmp"


def _logger_or_default(logger: Optional[logging.Logger]) -> logging.Logger:
    return logger if logger is not None else logging.getLogger("photo_manager.transfer")


def _durable_sync(fd: int, logger: logging.Logger, *, what: str) -> None:
    """Synchronize using macOS full fsync, with a logged safe fallback.

    Darwin supplies ``F_FULLFSYNC``.  Other supported development platforms
    do not, so use regular fsync there; this does not affect production macOS
    behavior.  Once F_FULLFSYNC is available, only an OSError triggers the
    fallback as required.
    """
    command = getattr(fcntl, "F_FULLFSYNC", None)
    if command is None:
        logger.warning("F_FULLFSYNC is unavailable; using fsync for %s", what)
        os.fsync(fd)
        return
    try:
        fcntl.fcntl(fd, command)
    except OSError as exc:
        logger.warning("F_FULLFSYNC failed for %s (%s); using fsync", what, exc)
        os.fsync(fd)


def _hash_fd(fd: int, *, chunk_size: int) -> str:
    digest = hashlib.sha256()
    while True:
        block = os.read(fd, chunk_size)
        if not block:
            return digest.hexdigest()
        digest.update(block)


def _source_unchanged(before: os.stat_result, after: os.stat_result) -> bool:
    return before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns


def _safe_unlink_created_part(part: Path, resources: RunResources, logger: logging.Logger) -> None:
    """Remove only the registered destination temporary file of this run."""
    try:
        part.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("Could not remove this run's temporary file: %s", part)
    finally:
        resources.unregister_part_file(part)


def _part_path(destination_root: Path, destination: Path) -> Path:
    # Only a basename is used under the private directory.  The destination
    # comes from naming.py, but reject surprising paths at this write boundary.
    if not _PART_NAME.match(destination.name + ".part"):
        raise OperationalError("destination filename is not valid for a managed temporary file: {0}".format(destination))
    return management_tmp_dir(destination_root) / (destination.name + ".part")


def cleanup_stale_parts(destination_root: Path, *, logger: Optional[logging.Logger] = None) -> int:
    """Delete only direct, regular, validly named files in our tmp directory.

    In particular this intentionally does *not* recurse, follow symlinks, or
    interpret arbitrary ``*.part`` files elsewhere in the archive as ours.
    """
    log = _logger_or_default(logger)
    tmp = management_tmp_dir(destination_root)
    try:
        entries = list(tmp.iterdir())
    except FileNotFoundError:
        return 0
    except OSError as exc:
        raise OperationalError("cannot inspect temporary directory {0}: {1}".format(tmp, exc))
    removed = 0
    for path in entries:
        if not _PART_NAME.match(path.name):
            continue
        try:
            mode = os.lstat(str(path)).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("Cannot inspect possible temporary file %s: %s", path, exc)
            continue
        if not stat.S_ISREG(mode):
            log.warning("Leaving non-regular possible temporary file untouched: %s", path)
            continue
        try:
            path.unlink()
            removed += 1
            log.info("Removed stale managed temporary file: %s", path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            log.warning("Could not remove stale managed temporary file %s: %s", path, exc)
    return removed


def transfer_file(
    plan: TransferPlan,
    destination_root: Path,
    resources: RunResources,
    *,
    logger: Optional[logging.Logger] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> TransferResult:
    """Copy and independently verify one planned file without replacement.

    This accepts only a COPY plan.  A concurrent creator of the final name is
    reported as ``CONFLICT`` after this run's private temporary file is
    removed, allowing the import layer to re-evaluate duplicates safely.
    """
    log = _logger_or_default(logger)
    if plan.action is not PlannedAction.COPY:
        return TransferResult(TransferStatus.SKIPPED, plan.source.path, plan.destination, message="plan does not request a copy")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    root = destination_root.absolute()
    destination = plan.destination.absolute()
    try:
        destination.relative_to(root)
    except ValueError:
        raise OperationalError("planned destination is outside archive root: {0}".format(destination))
    part: Optional[Path] = None
    try:
        # Directory creation only touches the verified archive destination.
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = management_tmp_dir(root)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        part = _part_path(root, destination)

        # O_EXCL makes both stale name collisions and concurrent writers safe:
        # neither is overwritten and neither is eligible for our cleanup.
        part_fd = os.open(str(part), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        resources.register_part_file(part)
        try:
            before = plan.source.path.stat()
            source_digest = hashlib.sha256()
            with plan.source.path.open("rb") as source, os.fdopen(part_fd, "wb", closefd=True) as output:
                part_fd = -1
                while True:
                    block = source.read(chunk_size)
                    if not block:
                        break
                    source_digest.update(block)
                    output.write(block)
                output.flush()
                _durable_sync(output.fileno(), log, what="temporary file")
            after = plan.source.path.stat()
        finally:
            if part_fd >= 0:
                os.close(part_fd)

        if not _source_unchanged(before, after):
            raise OperationalError("source changed while it was being copied: {0}".format(plan.source.path))

        verify_fd = os.open(str(part), os.O_RDONLY)
        try:
            nocache = getattr(fcntl, "F_NOCACHE", None)
            if nocache is None:
                log.warning("F_NOCACHE is unavailable; verification may use cache: %s", part)
            else:
                try:
                    fcntl.fcntl(verify_fd, nocache, 1)
                except OSError as exc:
                    log.warning("F_NOCACHE failed for %s: %s", part, exc)
            copied_digest = _hash_fd(verify_fd, chunk_size=chunk_size)
        finally:
            os.close(verify_fd)
        if source_digest.hexdigest() != copied_digest:
            raise OperationalError("copied file hash does not match source: {0}".format(plan.source.path))

        os.utime(str(part), ns=(before.st_atime_ns, before.st_mtime_ns))
        try:
            os.link(str(part), str(destination))
        except FileExistsError:
            _safe_unlink_created_part(part, resources, log)
            return TransferResult(TransferStatus.CONFLICT, plan.source.path, destination, copied_digest, "final destination appeared during transfer")
        part.unlink()
        resources.unregister_part_file(part)

        directory_fd = os.open(str(destination.parent), os.O_RDONLY)
        try:
            _durable_sync(directory_fd, log, what="destination directory")
        finally:
            os.close(directory_fd)
        return TransferResult(TransferStatus.COPIED, plan.source.path, destination, copied_digest)
    except FileExistsError:
        # This can only be the O_EXCL temp creation collision.  It is not ours
        # to delete, and final data has not been touched.
        return TransferResult(TransferStatus.CONFLICT, plan.source.path, destination, message="managed temporary name already exists")
    except (OSError, OperationalError) as exc:
        if part is not None:
            _safe_unlink_created_part(part, resources, log)
        return TransferResult(TransferStatus.FAILED, plan.source.path, destination, message=str(exc))
