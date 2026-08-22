"""Non-destructive archive-to-archive mirroring.

The primary archive is treated as read-only, just like an SD card: this
module contains no operation that creates, unlinks, renames, chmods, or utimes
a file below it.  A complete source-ledger verification is deliberately the
gate before any mirror data or ledger is changed.
"""
from __future__ import annotations

import hashlib
import logging
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Sequence, Tuple

from .config import Config, apply_cli_overrides, load_config
from .discovery import SourceFile, SourceKind
from .ledger import LedgerError, LedgerRecord, load_ledger, replace_ledger
from .locking import acquire_mirror_locks
from .metadata import CaptureTime
from .naming import PlannedAction, TransferPlan
from .runtime import OperationalError, RunResources, UsageError
from .transfer import TransferStatus, transfer_file
from .volumes import ensure_capacity, ensure_hard_links, ensure_writable, validate_volume


@dataclass(frozen=True)
class MirrorSummary:
    copied: int = 0
    skipped: int = 0
    warnings: int = 0
    failures: int = 0
    dry_run: bool = False


def _safe_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    path = root.absolute().joinpath(*pure.parts)
    try:
        path.relative_to(root.absolute())
    except ValueError:
        raise OperationalError("ledger path escapes archive root: {0!r}".format(relative))
    return path


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise OperationalError("cannot hash {0}: {1}".format(path, exc))
    return digest.hexdigest()


def _is_regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(str(path)).st_mode)
    except OSError:
        return False


def _source_records(root: Path, subdir: str) -> Dict[str, LedgerRecord]:
    """Strictly validate every source record and source Camera file.

    A source archive with a missing, modified, symlinked, or unregistered
    Camera file is not a valid mirror source.  This happens before any target
    write probe, lock, temporary, data copy, or ledger replacement.
    """
    records = load_ledger(root)
    for relative, record in records.items():
        path = _safe_path(root, relative)
        if not _is_regular(path):
            raise OperationalError("source ledger file is missing or not regular: {0}".format(relative))
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise OperationalError("cannot stat source ledger file {0}: {1}".format(relative, exc))
        if size != record.size or _hash(path) != record.digest:
            raise OperationalError("source ledger file does not match checksum: {0}".format(relative))

    camera = root / subdir
    if camera.exists() and not camera.is_dir():
        raise OperationalError("source archive subdirectory is not a directory: {0}".format(camera))
    if camera.is_dir():
        for base, directories, names in os.walk(str(camera), followlinks=False):
            directories[:] = [name for name in directories if not (Path(base) / name).is_symlink()]
            for name in names:
                path = Path(base) / name
                if path.is_symlink() or not _is_regular(path):
                    raise OperationalError("source archive contains unsafe non-regular file: {0}".format(path))
                relative = path.relative_to(root).as_posix()
                if relative not in records:
                    raise OperationalError("source archive contains unregistered file: {0}".format(relative))
    return records


def _plans(source_root: Path, target_root: Path, records: Dict[str, LedgerRecord]) -> Tuple[TransferPlan, ...]:
    result: List[TransferPlan] = []
    for relative, record in sorted(records.items()):
        source = _safe_path(source_root, relative)
        destination = _safe_path(target_root, relative)
        value = datetime.fromisoformat(record.captured_at)
        source_file = SourceFile(source, SourceKind.STILL, record.size, source.stat().st_mtime)
        result.append(TransferPlan(source_file, CaptureTime(value, "ledger"), destination,
                                   Path(*PurePosixPath(relative).parts), PlannedAction.COPY, False))
    return tuple(result)


def _target_matches(path: Path, record: LedgerRecord) -> bool:
    if not _is_regular(path):
        return False
    try:
        return path.stat().st_size == record.size and _hash(path) == record.digest
    except OSError:
        return False


def _target_extras(root: Path, subdir: str, records: Dict[str, LedgerRecord]) -> List[str]:
    extras: List[str] = []
    # Do not confine this to Camera: a mirror-only Phone (or future archive
    # role) file is equally important to report, and is still never removed.
    if not root.is_dir():
        return extras
    for base, directories, names in os.walk(str(root), followlinks=False):
        directories[:] = [name for name in directories
                           if name != "_photo-manager" and not (Path(base) / name).is_symlink()]
        for name in names:
            path = Path(base) / name
            relative = path.relative_to(root).as_posix()
            if relative not in records:
                extras.append(relative)
    return sorted(extras)


def _verify_target_data(root: Path, records: Dict[str, LedgerRecord]) -> None:
    for relative, record in records.items():
        if not _target_matches(_safe_path(root, relative), record):
            raise OperationalError("mirror verification failed: {0}".format(relative))


def _verify_target(root: Path, records: Dict[str, LedgerRecord]) -> None:
    _verify_target_data(root, records)
    installed = load_ledger(root)
    if installed != records:
        raise OperationalError("mirror checksum ledger differs from source ledger")


def mirror_handler(args: object, resources: RunResources, logger: logging.Logger) -> int:
    """Mirror a verified primary archive without altering it or deleting data."""
    config = apply_cli_overrides("mirror", args, load_config(getattr(args, "config", None)))
    assert config.mirror is not None
    source_info = validate_volume(config.dest.root, config.dest.volume_uuid)
    target_info = validate_volume(config.mirror.root, config.mirror.volume_uuid)
    if source_info.volume_uuid.casefold() == target_info.volume_uuid.casefold():
        raise UsageError("mirror source and destination must be different volumes")

    # This read-only, all-record validation is the hard gate protecting the
    # mirror destination from a damaged or incomplete primary archive.
    try:
        records = _source_records(config.dest.root, config.dest.subdir)
    except (LedgerError, OperationalError) as exc:
        logger.error("Source archive is not safe to mirror: %s", exc)
        return 1
    plans = _plans(config.dest.root, config.mirror.root, records)
    existing = 0
    needed = 0
    failures = 0
    for plan in plans:
        record = records[plan.relative_destination.as_posix()]
        if plan.destination.exists() or plan.destination.is_symlink():
            if _target_matches(plan.destination, record):
                existing += 1
            else:
                failures += 1
                logger.error("Mirror destination conflict (will not overwrite): %s", plan.relative_destination.as_posix())
        else:
            needed += plan.source.size
    extras = _target_extras(config.mirror.root, config.mirror.subdir, records)
    for relative in extras:
        logger.warning("Mirror-only file retained (not deleted): %s", relative)

    dry_run = bool(getattr(args, "dry_run", False))
    logger.info("Mirror plan: copy %d / skip %d / warning %d / failure %d", len(plans) - existing - failures, existing, len(extras), failures)
    if dry_run:
        logger.info("DRY-RUN: no mirror data, ledger, or management files were changed")
        return 1 if failures else 0
    if failures:
        # Do not create a lock or a private temporary after an observed target
        # conflict; nothing on either archive needs changing to report it.
        return 1

    ensure_writable(config.mirror.root)
    ensure_hard_links(config.mirror.root)
    ensure_capacity(config.mirror.root, needed, config.free_space_margin)
    acquire_mirror_locks(((source_info.volume_uuid, config.dest.root),
                          (target_info.volume_uuid, config.mirror.root)), resources)

    # Recheck the complete source after locking.  A source change during the
    # earlier read-only pass cannot be allowed to start target modification.
    try:
        records = _source_records(config.dest.root, config.dest.subdir)
    except (LedgerError, OperationalError) as exc:
        logger.error("Source archive changed or is invalid: %s", exc)
        return 1
    plans = _plans(config.dest.root, config.mirror.root, records)
    copied = skipped = 0
    for plan in plans:
        record = records[plan.relative_destination.as_posix()]
        if plan.destination.exists() or plan.destination.is_symlink():
            if _target_matches(plan.destination, record):
                skipped += 1
                continue
            logger.error("Mirror destination conflict (will not overwrite): %s", plan.relative_destination.as_posix())
            failures += 1
            continue
        result = transfer_file(plan, config.mirror.root, resources, logger=logger)
        if result.status is TransferStatus.COPIED:
            copied += 1
        else:
            failures += 1
            logger.error("Mirror copy failed for %s: %s", plan.relative_destination.as_posix(), result.message or result.status.value)
    if failures:
        logger.error("Mirror data copy failed; destination ledger was not updated")
        return 1
    try:
        # Only a fully copied, verified set is allowed to publish the source
        # snapshot.  Atomic replacement is management-file-only.
        _verify_target_data(config.mirror.root, records)
        replace_ledger(config.mirror.root, records.values())
        _verify_target(config.mirror.root, records)
    except (LedgerError, OperationalError) as exc:
        logger.error("Mirror final verification failed: %s", exc)
        return 1
    logger.info("Mirror summary: copied %d / skipped %d / warning %d / failure 0", copied, skipped, len(extras))
    return 0
