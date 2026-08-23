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


def _source_ledger(root: Path) -> Dict[str, LedgerRecord]:
    """Read and syntax-check the source ledger without hashing any data.

    This is the pre-lock, read-only provisional pass of a real run.  Its
    results are used for display, for the capacity estimate and for failing
    early; they are never the basis for changing the mirror.  Specification
    step 3 (verify every transfer candidate against the ledger) happens after
    both locks are held, in :func:`_source_records`.
    """
    return load_ledger(root)


def _source_records(root: Path, subdir: str) -> Dict[str, LedgerRecord]:
    """Strictly validate every source record and source Camera file.

    A source archive with a missing, modified, symlinked, or unregistered
    Camera file is not a valid mirror source.  This is specification step 3
    and is the hard gate in front of every mirror temporary, data copy and
    ledger replacement.
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
    """Turn validated records into copy plans, reading only the source."""
    result: List[TransferPlan] = []
    for relative, record in sorted(records.items()):
        source = _safe_path(source_root, relative)
        destination = _safe_path(target_root, relative)
        value = datetime.fromisoformat(record.captured_at)
        # The provisional pass reaches this without having verified the source,
        # so a listed-but-absent file must be a reported failure, not a crash.
        try:
            mtime = source.stat().st_mtime
        except OSError as exc:
            raise OperationalError("cannot stat source ledger file {0}: {1}".format(relative, exc))
        source_file = SourceFile(source, SourceKind.STILL, record.size, mtime)
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


def _verify_mirror_data(root: Path, records: Dict[str, LedgerRecord]) -> None:
    """Hash every managed mirror file and compare it with the source ledger."""
    for relative, record in records.items():
        if not _target_matches(_safe_path(root, relative), record):
            raise OperationalError("mirror verification failed: {0}".format(relative))


def _verify_published_mirror(root: Path, records: Dict[str, LedgerRecord]) -> None:
    """Specification step 8: re-verify the mirror *after* publishing its ledger.

    This deliberately repeats the data verification of step 7 in addition to
    comparing the installed snapshot with the source ledger.  The two passes
    guard different boundaries -- step 7 gates publication, step 8 confirms
    what a later ``photo-verify`` of this mirror would now be checking against
    -- so the specification requires both even though they read the same
    bytes.  Merging them would need a specification and threat-model change
    first (see docs/plans/0002-review-remediation, F3-b).
    """
    _verify_mirror_data(root, records)
    installed = load_ledger(root)
    if installed != records:
        raise OperationalError("mirror checksum ledger differs from source ledger")


@dataclass(frozen=True)
class _Survey:
    """How one set of source records relates to the current mirror."""

    plans: Tuple[TransferPlan, ...]
    present: Tuple[TransferPlan, ...]
    missing: Tuple[TransferPlan, ...]
    conflicts: Tuple[TransferPlan, ...]
    extras: Tuple[str, ...]
    needed: int


def _survey(config: Config, records: Dict[str, LedgerRecord], logger: logging.Logger, *, report: bool) -> _Survey:
    """Classify every record against the mirror, without changing anything.

    ``report`` is true for the pre-lock provisional pass, which is what the
    operator sees; the post-lock pass recomputes the same classification from
    the verified records and stays quiet about what was already announced.
    """
    assert config.mirror is not None
    plans = _plans(config.dest.root, config.mirror.root, records)
    present: List[TransferPlan] = []
    missing: List[TransferPlan] = []
    conflicts: List[TransferPlan] = []
    needed = 0
    for plan in plans:
        record = records[plan.relative_destination.as_posix()]
        if plan.destination.exists() or plan.destination.is_symlink():
            if _target_matches(plan.destination, record):
                present.append(plan)
            else:
                conflicts.append(plan)
                logger.error("Mirror destination conflict (will not overwrite): %s",
                             plan.relative_destination.as_posix())
        else:
            missing.append(plan)
            needed += plan.source.size
    extras = _target_extras(config.mirror.root, config.mirror.subdir, records)
    if report:
        for relative in extras:
            logger.warning("Mirror-only file retained (not deleted): %s", relative)
    return _Survey(plans, tuple(present), tuple(missing), tuple(conflicts), tuple(extras), needed)


def mirror_handler(args: object, resources: RunResources, logger: logging.Logger) -> int:
    """Mirror a verified primary archive without altering it or deleting data."""
    config = apply_cli_overrides("mirror", args, load_config(getattr(args, "config", None)))
    assert config.mirror is not None
    source_info = validate_volume(config.dest.root, config.dest.volume_uuid)
    target_info = validate_volume(config.mirror.root, config.mirror.volume_uuid)
    if source_info.volume_uuid.casefold() == target_info.volume_uuid.casefold():
        raise UsageError("mirror source and destination must be different volumes")

    dry_run = bool(getattr(args, "dry_run", False))
    # Read-only provisional pass.  A dry-run's whole purpose is to answer "is
    # the source healthy?", so it verifies every record and file here.  A real
    # run only parses the ledger: the specification's order is check paths ->
    # lock -> verify the source, and the pre-lock plan is provisional anyway
    # because the source may change before the locks are held.
    try:
        if dry_run:
            records = _source_records(config.dest.root, config.dest.subdir)
        else:
            records = _source_ledger(config.dest.root)
    except (LedgerError, OperationalError) as exc:
        logger.error("Source archive is not safe to mirror: %s", exc)
        return 1
    try:
        provisional = survey = _survey(config, records, logger, report=True)
    except OperationalError as exc:
        logger.error("Source archive is not safe to mirror: %s", exc)
        return 1

    logger.info("Mirror plan: copy %d / skip %d / warning %d / failure %d",
                len(survey.missing), len(survey.present), len(survey.extras), len(survey.conflicts))
    if dry_run:
        logger.info("DRY-RUN: no mirror data, ledger, or management files were changed")
        return 1 if survey.conflicts else 0
    if survey.conflicts:
        # Do not create a lock or a private temporary after an observed target
        # conflict; nothing on either archive needs changing to report it.
        return 1

    ensure_writable(config.mirror.root)
    ensure_hard_links(config.mirror.root)
    ensure_capacity(config.mirror.root, survey.needed, config.free_space_margin)
    acquire_mirror_locks(((source_info.volume_uuid, config.dest.root),
                          (target_info.volume_uuid, config.mirror.root)), resources)

    # Specification step 3, now that both locks are held: verify the complete
    # source, then recompute the plan, the target conflicts, the extras and the
    # required capacity from those verified records.  Everything above was
    # provisional, and nothing on the mirror has been changed yet.
    try:
        records = _source_records(config.dest.root, config.dest.subdir)
        survey = _survey(config, records, logger, report=False)
    except (LedgerError, OperationalError) as exc:
        logger.error("Source archive changed or is invalid: %s", exc)
        return 1
    announced = set(provisional.extras)
    for relative in survey.extras:
        if relative not in announced:
            logger.warning("Mirror-only file retained (not deleted): %s", relative)
    if survey.conflicts:
        logger.error("Mirror destination changed after the provisional pass; no data was copied")
        return 1
    try:
        ensure_capacity(config.mirror.root, survey.needed, config.free_space_margin)
    except UsageError as exc:
        # The preflight already accepted this destination, so a shortfall here
        # is an external change during the run: an operation failure, not a
        # usage error.  Still nothing has been copied.
        logger.error("Mirror destination state changed after the preflight: %s", exc)
        return 1

    copied = 0
    skipped = len(survey.present)
    failures = 0
    copy_warnings = 0
    for plan in survey.missing:
        result = transfer_file(plan, config.mirror.root, resources, logger=logger)
        # Reported separately from failures: the file is published either way.
        for warning in result.warnings:
            copy_warnings += 1
            logger.warning("%s", warning)
        if result.status is TransferStatus.COPIED:
            copied += 1
        else:
            failures += 1
            logger.error("Mirror copy failed for %s: %s", plan.relative_destination.as_posix(), result.message or result.status.value)
    if failures:
        logger.error("Mirror data copy failed; destination ledger was not updated")
        return 1
    try:
        # Step 7: only a fully copied, verified set may publish the source
        # snapshot.  Atomic replacement is management-file-only.
        _verify_mirror_data(config.mirror.root, records)
        # Both archive locks are held here, so a checksums.tsv.mirror.part
        # left by an interrupted run is this tool's to discard.
        replace_ledger(config.mirror.root, records.values(), allow_stale_temporary=True)
        # Step 8: re-verify the data now that the ledger is published, and
        # confirm the installed snapshot is the source ledger.
        _verify_published_mirror(config.mirror.root, records)
    except (LedgerError, OperationalError) as exc:
        logger.error("Mirror final verification failed: %s", exc)
        return 1
    logger.info("Mirror summary: copied %d / skipped %d / warning %d / failure 0", copied, skipped, len(survey.extras) + copy_warnings)
    return 0
