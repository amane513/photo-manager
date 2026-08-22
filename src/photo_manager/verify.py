"""Read-only archive verification for ``photo-verify``.

This module never creates, removes, renames, or updates archive photographs,
the checksum ledger, or an SD-card file.  Its only coordination operation is
the shared archive lock acquired by :func:`verify_handler`.
"""
from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Iterator, Optional, Tuple

from .config import Config, apply_cli_overrides, load_config
from .ledger import LedgerError, LedgerRecord, load_ledger
from .locking import acquire_lock
from .runtime import RunResources, UsageError
from .volumes import validate_volume


_YEAR = re.compile(r"^[0-9]{4}$")
_MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class VerifySummary:
    checked: int = 0
    failures: int = 0
    warnings: int = 0


def _scope(args: object) -> Tuple[Optional[str], Optional[str]]:
    """Return (year, month), rejecting values which cannot name archive dirs."""
    year = getattr(args, "year", None)
    month = getattr(args, "month", None)
    if year is not None:
        if not _YEAR.fullmatch(year):
            raise UsageError("--year must be YYYY")
        return year, None
    if month is not None:
        if not _MONTH.fullmatch(month):
            raise UsageError("--month must be YYYY-MM")
        return month[:4], month
    return None, None


def _subdir_parts(config: Config) -> Tuple[str, ...]:
    # Config already rejects absolute and parent paths.  Posix conversion is
    # intentional because ledger paths, on every supported platform, are POSIX.
    parts = PurePosixPath(config.dest.subdir.replace("\\", "/")).parts
    if not parts or any(part in (".", "..", "") for part in parts):
        raise UsageError("configured destination subdir is invalid")
    return parts


def _record_in_scope(record: LedgerRecord, subdir: Tuple[str, ...], year: Optional[str], month: Optional[str]) -> bool:
    parts = PurePosixPath(record.path).parts
    if parts[:len(subdir)] != subdir:
        return False
    # Archive files have the stable subdir/YYYY/YYYY-MM/file layout.  Entries
    # elsewhere remain valid ledger entries, but are not silently treated as a
    # requested month/year verification target.
    tail = parts[len(subdir):]
    if len(tail) < 3:
        return False
    if year is not None and tail[0] != year:
        return False
    if month is not None and tail[1] != month:
        return False
    return True


def _archive_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _hash_nocache(path: Path, logger: logging.Logger, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a separately opened descriptor, asking macOS to bypass its cache."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        nocache = getattr(fcntl, "F_NOCACHE", None)
        if nocache is None:
            logger.warning("F_NOCACHE is unavailable; verification may use cache: %s", path)
        else:
            try:
                fcntl.fcntl(fd, nocache, 1)
            except OSError as exc:
                logger.warning("F_NOCACHE failed for %s: %s", path, exc)
        digest = hashlib.sha256()
        while True:
            block = os.read(fd, chunk_size)
            if not block:
                break
            digest.update(block)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _verify_record(root: Path, record: LedgerRecord, logger: logging.Logger) -> Optional[str]:
    path = root.joinpath(*PurePosixPath(record.path).parts)
    try:
        info = path.stat()
    except FileNotFoundError:
        return "missing registered file"
    except OSError as exc:
        return "cannot inspect registered file: {0}".format(exc)
    if not path.is_file():
        return "registered path is not a regular file"
    if info.st_size != record.size:
        return "size mismatch (ledger {0}, file {1})".format(record.size, info.st_size)
    try:
        digest = _hash_nocache(path, logger)
    except OSError as exc:
        return "cannot hash registered file: {0}".format(exc)
    if digest != record.digest:
        return "sha256 mismatch"
    return None


def _scope_root(root: Path, subdir: Tuple[str, ...], year: Optional[str], month: Optional[str]) -> Path:
    result = root.joinpath(*subdir)
    if year is not None:
        result = result / year
    if month is not None:
        result = result / month
    return result


def _iter_regular_files(directory: Path, logger: logging.Logger) -> Iterator[Path]:
    """Walk directory contents without following directory symlinks."""
    if not directory.exists():
        return
    try:
        for current, dirs, files in os.walk(str(directory), followlinks=False):
            current_path = Path(current)
            # A symlink directory is not followed by os.walk, and is an extra
            # archive item itself; report it through the caller as a warning.
            for name in files:
                candidate = current_path / name
                try:
                    if candidate.is_file():
                        yield candidate
                    else:
                        logger.warning("Extra non-regular archive entry: %s", candidate)
                except OSError as exc:
                    logger.warning("Cannot inspect archive entry %s: %s", candidate, exc)
    except OSError as exc:
        logger.warning("Cannot scan archive directory %s: %s", directory, exc)


def _scan_unregistered(root: Path, ledger: Dict[str, LedgerRecord], subdir: Tuple[str, ...], year: Optional[str], month: Optional[str], logger: logging.Logger) -> VerifySummary:
    """Find formal archive files without records and out-of-tree extras.

    ``*.part`` is intentionally ignored for compatibility with pre-management
    temporary files.  It is never removed.  Files in the selected Camera tree
    without records are failures; ordinary files outside that tree are merely
    warnings because they are not archive candidates.
    """
    checked = failures = warnings = 0
    directory = _scope_root(root, subdir, year, month)
    for path in _iter_regular_files(directory, logger):
        relative = _archive_relative(path, root)
        if path.name.endswith(".part"):
            logger.warning("Ignoring leftover temporary file: %s", relative)
            warnings += 1
            continue
        checked += 1
        if relative not in ledger:
            logger.error("Unregistered archive file: %s", relative)
            failures += 1

    # Warn about ordinary archive-root files (including paths outside subdir),
    # but never turn them into a failure for a month/year scoped check.
    try:
        children = list(root.iterdir())
    except OSError as exc:
        logger.warning("Cannot inspect archive root for extra files: %s", exc)
        return VerifySummary(checked, failures, warnings + 1)
    configured = subdir[0]
    for child in children:
        if child.name == "_photo-manager" or child.name == configured:
            continue
        logger.warning("Extra file or directory outside archive subdir: %s", child.name)
        warnings += 1
    return VerifySummary(checked, failures, warnings)


def verify_handler(args: object, resources: RunResources, logger: logging.Logger) -> int:
    """Verify archive contents without modifying photographs or ledger data."""
    config = apply_cli_overrides("verify", args, load_config(getattr(args, "config", None)))
    year, month = _scope(args)
    validate_volume(config.dest.root, config.dest.volume_uuid)
    # The lock is intentionally acquired before the ledger is read so an
    # import/mirror cannot alter it halfway through this verification.
    acquire_lock(config.dest.root, exclusive=False, resources=resources)
    try:
        ledger = load_ledger(config.dest.root, repair_tail=False)
    except LedgerError as exc:
        logger.error("Ledger is invalid: %s", exc)
        return 1

    subdir = _subdir_parts(config)
    # With no range, the ledger itself is the contract: validate every row,
    # even a legacy row outside today's configured archive subdirectory.
    selected = (list(ledger.values()) if year is None
                else [record for record in ledger.values() if _record_in_scope(record, subdir, year, month)])
    failures = warnings = 0
    for record in selected:
        failure = _verify_record(config.dest.root, record, logger)
        if failure is not None:
            logger.error("Verification failed for %s: %s", record.path, failure)
            failures += 1

    scanned = _scan_unregistered(config.dest.root, ledger, subdir, year, month, logger)
    failures += scanned.failures
    warnings += scanned.warnings
    logger.info("Verification summary: checked %d registered file(s), scanned %d archive file(s), warning %d, failure %d",
                len(selected), scanned.checked, warnings, failures)
    return 1 if failures else 0
