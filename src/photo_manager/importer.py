"""Integration for the safe, one-way ``photo-import`` command.

The source card is deliberately passed only to read-only discovery, metadata,
hashing and stat calls.  This module contains no source-side create, unlink,
rename, chmod, or utime operation.  Ejection is the sole source-volume action
and is attempted only after :func:`should_eject` accepts a complete run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import Config, apply_cli_overrides, load_config
from .discovery import DiscoveryIssue, discover_files
from .ledger import (LedgerError, LedgerRecord, append_record, inspect_ledger, load_ledger,
                     make_record, supplement_record)
from .locking import acquire_lock
from .metadata import Runner, determine_capture_times
from .naming import DigestCache, NamingError, PlannedAction, TransferPlan, build_transfer_plans
from .runtime import OperationalError, RunResources, UsageError
from .transfer import TransferResult, TransferStatus, cleanup_stale_parts, transfer_file
from .volumes import (ensure_capacity, ensure_exiftool, ensure_hard_links,
                      ensure_writable, validate_source, validate_volume)


@dataclass(frozen=True)
class ImportSummary:
    copied: int = 0
    skipped: int = 0
    warnings: int = 0
    failures: int = 0
    ledger_complete: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class VerifiedTransfer:
    """A finished file together with the digest *this run* verified for it.

    ``digest`` is the copied file's re-read digest for a COPIED plan and the
    existing archive file's digest for a SKIP plan.  Keeping the two together
    is what lets the final ledger check compare records against evidence this
    run produced instead of hashing the pair again.
    """

    plan: TransferPlan
    digest: str


def should_eject(summary: ImportSummary, *, enabled: bool) -> bool:
    """Pure eject policy; never infer success from a display message."""
    return enabled and not summary.dry_run and summary.failures == 0 and summary.ledger_complete


def _log_directory(logger: logging.Logger) -> Optional[Path]:
    for handler in logger.handlers:
        filename = getattr(handler, "baseFilename", None)
        if filename:
            return Path(filename).parent
    # ``cli.main`` always configures a file handler.  Returning None also
    # keeps a directly embedded caller safe: load_ledger then refuses a tail
    # repair rather than modifying the ledger without a durable backup.
    return None


def _issue(logger: logging.Logger, issue: DiscoveryIssue, *, warning: bool) -> None:
    method = logger.warning if warning else logger.error
    method("%s: %s", issue.path, issue.message)


def _build_plans(config: Config, source: Path, ledger: Dict[str, LedgerRecord], logger: logging.Logger,
                 *, report: bool = True, runner: Optional[Runner] = None,
                 digest_cache: Optional[DigestCache] = None) -> Tuple[Tuple[TransferPlan, ...], int, int]:
    """Plan the run.  ``report`` is false for the provisional preflight pass so
    that per-file issues are announced once, by the authoritative pass.

    ``digest_cache`` is shared between the provisional and the authoritative
    pass.  Both passes take exactly the same decisions on the same code path;
    the cache only spares a re-read of a file that has not changed between
    them.

    ``runner`` overrides how exiftool is executed.  It exists so an end-to-end
    test can drive the real discovery/metadata/naming/transfer/ledger path
    with a stand-in for exiftool; ``None`` keeps the production default.
    """
    discovered = discover_files(source)
    failures = len(discovered.failures)
    metadata = (determine_capture_times(discovered.files, config.exiftool) if runner is None
                else determine_capture_times(discovered.files, config.exiftool, runner=runner))
    failures += len(metadata.failures)
    warnings = len(metadata.warnings)
    if report:
        for issue in discovered.failures:
            _issue(logger, issue, warning=False)
        for issue in metadata.failures:
            _issue(logger, issue, warning=False)
        for issue in metadata.warnings:
            _issue(logger, issue, warning=True)
    usable = [item for item in discovered.files if item.path in metadata.capture_times]
    try:
        plans = build_transfer_plans(
            usable, metadata.capture_times, config.dest.root, subdir=config.dest.subdir,
            ledger_has_record=lambda relative: relative.as_posix() in ledger,
            digest_cache=digest_cache,
        )
    except NamingError as exc:
        raise OperationalError("cannot safely create import plan: {0}".format(exc))
    for plan in plans:
        if plan.collision_detected and plan.action is PlannedAction.COPY:
            warnings += 1
            if report:
                logger.warning("Name collision has different content; preserving both as: %s", plan.relative_destination.as_posix())
    return plans, warnings, failures


def _planned_copy_bytes(plans: Iterable[TransferPlan]) -> int:
    return sum(plan.source.size for plan in plans if plan.action is PlannedAction.COPY)


def _print_plan(logger: logging.Logger, plans: Iterable[TransferPlan]) -> None:
    for plan in plans:
        logger.info("PLAN %s %s -> %s", plan.action.value, plan.source.path, plan.relative_destination.as_posix())


def _record_for(plan: TransferPlan, digest: str):
    return make_record(plan.relative_destination.as_posix(), digest, plan.source.size, plan.capture_time.value)


def _verify_records(root: Path, results: Sequence[VerifiedTransfer], ledger: Dict[str, LedgerRecord],
                    digests: DigestCache, logger: logging.Logger) -> bool:
    """Confirm every finished file and its ledger entry, just before ejecting.

    Three independent things are checked for every file:

    1. a ledger record exists, its size matches the source and the archive
       file's *actual* size, and its digest is the one this run verified;
    2. the archive file is hashed **again** here, right before the eject
       decision, and must equal the ledger digest.  ``flock`` is advisory, so
       a digest measured earlier in this run is never accepted as a substitute
       for this final read;
    3. the source still matches.  Its digest is only re-read when the file is
       not provably the one that produced the verified digest -- an unchanged
       size and mtime is what allows the copy-time or skip-time digest to
       stand in.  Any change means a fresh hash and, on mismatch, a failure.
    """
    complete = True
    for entry in results:
        plan = entry.plan
        key = plan.relative_destination.as_posix()
        record = ledger.get(key)
        if record is None:
            logger.error("Missing checksum record: %s", key)
            complete = False
            continue
        try:
            destination_size = plan.destination.stat().st_size
        except OSError as exc:
            logger.error("Cannot recheck %s: %s", key, exc)
            complete = False
            continue
        if record.size != plan.source.size or destination_size != record.size or record.digest != entry.digest:
            logger.error("Final checksum recheck failed: %s", key)
            complete = False
            continue
        try:
            destination_digest = digests.measure(plan.destination)
            source_digest = digests.reuse(plan.source.path)
            if source_digest is None:
                logger.warning("Source is not provably unchanged since it was verified; hashing it again: %s",
                               plan.source.path)
                source_digest = digests.measure(plan.source.path)
        except (OSError, NamingError) as exc:
            logger.error("Cannot recheck %s: %s", key, exc)
            complete = False
            continue
        if destination_digest != record.digest or source_digest != record.digest:
            logger.error("Final checksum recheck failed: %s", key)
            complete = False
    return complete


def _transfer_with_replan(plan: TransferPlan, config: Config, ledger: Dict[str, LedgerRecord], resources: RunResources,
                          digests: DigestCache, logger: logging.Logger) -> Tuple[TransferPlan, TransferResult]:
    """Resolve a final-name race without ever replacing its winner."""
    current = plan
    for _attempt in range(100):
        result = transfer_file(current, config.dest.root, resources, logger=logger)
        if not result.needs_replan:
            return current, result
        logger.warning("Destination changed concurrently; rechecking collision: %s", current.destination)
        try:
            current = build_transfer_plans(
                [current.source], {current.source.path: current.capture_time}, config.dest.root,
                subdir=config.dest.subdir,
                ledger_has_record=lambda relative: relative.as_posix() in ledger,
                digest_cache=digests,
            )[0]
        except (NamingError, IndexError) as exc:
            return current, TransferResult(TransferStatus.FAILED, current.source.path, current.destination, message="cannot safely replan conflict: {0}".format(exc))
    return current, TransferResult(TransferStatus.FAILED, current.source.path, current.destination, message="too many concurrent destination conflicts")


def import_handler(args: object, resources: RunResources, logger: logging.Logger,
                   *, runner: Optional[Runner] = None) -> int:
    """Run the Phase-6 sequence, preserving the source card in all outcomes.

    ``runner`` is an explicit seam for exiftool execution.  ``cli.main`` never
    passes it, so production behaviour is unchanged; a test can supply one to
    exercise this whole path without patching a default argument that was
    already bound when the module was imported.

    The order follows the architecture's processing boundaries: read-only
    preflight (volume, source, exiftool, ledger inspection, provisional plan,
    write/hard-link probe, capacity) -> exclusive lock -> permitted management
    changes (tail repair, stale ``.part`` cleanup) -> authoritative replan and
    capacity recheck -> execution.  A preflight failure raises ``UsageError``
    (status 2) with nothing modified; a failure of the post-lock recheck is an
    operation failure (status 1) which still copies nothing.
    """
    config = apply_cli_overrides("import", args, load_config(getattr(args, "config", None)))
    validate_volume(config.dest.root, config.dest.volume_uuid)  # read-only preflight
    source = validate_source(config.source_root, destination=config.dest.root) if config.source_root else None
    if source is None:
        from .volumes import discover_source
        source = discover_source(config.dest.root)
    ensure_exiftool(config.exiftool)
    dry_run = bool(getattr(args, "dry_run", False))

    if dry_run:
        # Loading is read-only here.  A bad tail is reported rather than
        # repaired, because dry-run must not change even management state.
        try:
            ledger = load_ledger(config.dest.root)
        except LedgerError as exc:
            logger.error("Ledger is invalid (dry-run will not repair it): %s", exc)
            return 1
        plans, warnings, failures = _build_plans(config, source, ledger, logger, runner=runner)
        _print_plan(logger, plans)
        # No lock, no write/hard-link probe, no repair and no cleanup: only the
        # read-only capacity check runs, and an insufficient-space UsageError
        # propagates as the same preflight status the real run would report.
        ensure_capacity(config.dest.root, _planned_copy_bytes(plans), config.free_space_margin)
        summary = ImportSummary(skipped=sum(p.action is PlannedAction.SKIP for p in plans), warnings=warnings,
                                failures=failures, dry_run=True)
        logger.info("DRY-RUN summary: copy %d / skip %d / warning %d / failure %d; no state was changed",
                    sum(p.action is PlannedAction.COPY for p in plans), summary.skipped, warnings, failures)
        return 1 if failures else 0

    # Read-only preflight.  Nothing below may change data, the ledger, a
    # temporary file, or a management file until every check here passed: a
    # UsageError from this block therefore means "nothing was modified".  The
    # ledger is only *inspected*; a repairable tail is planned around and
    # repaired later, under the lock.
    try:
        inspection = inspect_ledger(config.dest.root, allow_repairable_tail=True)
    except LedgerError as exc:
        logger.error("Ledger is invalid and cannot be safely repaired: %s", exc)
        return 1
    if inspection.repairable_tail:
        logger.warning("Ledger has an incomplete final row; it will be repaired after locking the archive")
    # Digests measured while planning are carried into the authoritative pass
    # and the final check.  Re-hashing a full card once per pass is the
    # dominant cost of a re-import, and a size/mtime-guarded reuse removes it
    # without removing a comparison.
    digests = DigestCache()
    provisional = _build_plans(config, source, inspection.records, logger, report=False, runner=runner,
                               digest_cache=digests)[0]
    ensure_writable(config.dest.root)
    ensure_hard_links(config.dest.root)
    ensure_capacity(config.dest.root, _planned_copy_bytes(provisional), config.free_space_margin)

    # Every operation below this point may modify the verified archive, so the
    # lock is taken first: acquiring it creates the permanent lock file, which
    # is itself a management change and must follow the preflight.
    acquire_lock(config.dest.root, exclusive=True, resources=resources)
    try:
        # The exclusive lock above is what makes discarding a leftover
        # checksums.tsv.repair.part safe: no other run owns it.
        ledger = load_ledger(config.dest.root, repair_tail=True, log_dir=_log_directory(logger),
                             allow_stale_temporary=True)
    except LedgerError as exc:
        logger.error("Ledger is invalid and cannot be safely repaired: %s", exc)
        return 1
    try:
        removed = cleanup_stale_parts(config.dest.root, logger=logger)
        if removed:
            logger.info("Removed %d stale managed temporary file(s)", removed)
    except OperationalError as exc:
        logger.error("Could not clean stale managed temporary files: %s", exc)
        return 1
    # Replan after lock/repair; this is the authoritative execution plan.  It
    # runs the full comparison again -- only unchanged files skip re-reading.
    plans, warnings, failures = _build_plans(config, source, ledger, logger, runner=runner, digest_cache=digests)
    _print_plan(logger, plans)
    try:
        ensure_capacity(config.dest.root, _planned_copy_bytes(plans), config.free_space_margin)
    except UsageError as exc:
        # The preflight already accepted this destination, so a shortfall now
        # is an external change during the run: an operation failure, not a
        # usage error.  Nothing is copied and no record is appended.
        logger.error("Destination state changed after the preflight: %s", exc)
        return 1

    copied = skipped = 0
    final_results: List[VerifiedTransfer] = []

    def accept_skip(accepted: TransferPlan, *, replanned: bool) -> bool:
        """Record a verified duplicate, or refuse one without its digest."""
        if accepted.verified_digest is None:
            # A SKIP is only ever produced after the archive file was hashed
            # and found equal, so this cannot happen for a planned run.  If it
            # somehow does, refuse rather than report an unverified success.
            logger.error("FAILED %s: skipped duplicate has no verified digest",
                         accepted.relative_destination.as_posix())
            return False
        if accepted.ledger_missing:
            supplement_record(config.dest.root, relative_path=accepted.relative_destination.as_posix(),
                              source_path=accepted.source.path, captured_at=accepted.capture_time.value,
                              known=ledger)
        logger.info("SKIPPED verified duplicate%s: %s", " after replan" if replanned else "",
                    accepted.relative_destination.as_posix())
        final_results.append(VerifiedTransfer(accepted, accepted.verified_digest))
        return True

    for plan in plans:
        current = plan
        if plan.action is PlannedAction.SKIP:
            try:
                if accept_skip(plan, replanned=False):
                    skipped += 1
                else:
                    failures += 1
            except LedgerError as exc:
                failures += 1
                logger.error("FAILED to supplement checksum for %s: %s", plan.relative_destination, exc)
            continue
        current, result = _transfer_with_replan(plan, config, ledger, resources, digests, logger)
        # A copy can succeed and still report a problem worth surfacing, e.g.
        # a managed temporary that could not be removed after publication.
        for warning in result.warnings:
            warnings += 1
            logger.warning("%s", warning)
        if result.status is TransferStatus.COPIED:
            try:
                assert result.digest is not None
                # The copy verified this digest against the source it just
                # read, so the source may be remembered by it too.
                digests.remember(current.source.path, result.digest)
                # The exclusive lock is held, so the in-memory ledger is the
                # complete picture: no re-read of the whole file per record.
                append_record(config.dest.root, _record_for(current, result.digest), known=ledger)
                copied += 1
                logger.info("COPIED and verified: %s -> %s", current.source.path, current.relative_destination.as_posix())
                final_results.append(VerifiedTransfer(current, result.digest))
            except LedgerError as exc:
                failures += 1
                logger.error("FAILED to record checksum for %s: %s", current.relative_destination, exc)
        elif result.status is TransferStatus.SKIPPED:
            try:
                if accept_skip(current, replanned=True):
                    skipped += 1
                else:
                    failures += 1
            except LedgerError as exc:
                failures += 1
                logger.error("FAILED to supplement checksum for %s: %s", current.relative_destination, exc)
        else:
            failures += 1
            logger.error("FAILED %s: %s", current.source.path, result.message or result.status.value)

    # Reload catches a failed/partial append and makes the eject decision
    # depend on durable, parseable records rather than in-memory intent.
    try:
        final_ledger = load_ledger(config.dest.root)
        ledger_complete = (failures == 0 and len(final_results) == len(plans)
                           and _verify_records(config.dest.root, final_results, final_ledger, digests, logger))
    except LedgerError as exc:
        logger.error("Final ledger recheck failed: %s", exc)
        ledger_complete = False
    if not ledger_complete:
        failures += 1 if failures == 0 else 0
    summary = ImportSummary(copied, skipped, warnings, failures, ledger_complete)
    logger.info("Import summary: copied %d / skipped %d / warning %d / failure %d", copied, skipped, warnings, failures)
    if should_eject(summary, enabled=config.eject_after_import):
        # Import lazily to make the pure policy independently testable.
        from .volumes import eject_volume
        try:
            eject_volume(source)
        except OperationalError as exc:
            logger.error("Import succeeded but SD card eject failed: %s", exc)
            return 1
        logger.info("SD card ejected safely. Return it to the camera and use the camera's format function.")
    elif failures:
        logger.warning("SD card was not ejected because the import is incomplete.")
    else:
        logger.info("SD card was not ejected by configuration.")
    return 1 if failures else 0
