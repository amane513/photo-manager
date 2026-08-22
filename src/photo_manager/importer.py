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
from .ledger import LedgerError, LedgerRecord, append_record, load_ledger, make_record, supplement_record
from .locking import acquire_lock
from .metadata import determine_capture_times
from .naming import NamingError, PlannedAction, TransferPlan, build_transfer_plans, sha256_file
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


def _build_plans(config: Config, source: Path, ledger: Dict[str, LedgerRecord], logger: logging.Logger) -> Tuple[Tuple[TransferPlan, ...], int, int]:
    discovered = discover_files(source)
    failures = len(discovered.failures)
    for issue in discovered.failures:
        _issue(logger, issue, warning=False)
    metadata = determine_capture_times(discovered.files, config.exiftool)
    failures += len(metadata.failures)
    warnings = len(metadata.warnings)
    for issue in metadata.failures:
        _issue(logger, issue, warning=False)
    for issue in metadata.warnings:
        _issue(logger, issue, warning=True)
    usable = [item for item in discovered.files if item.path in metadata.capture_times]
    try:
        plans = build_transfer_plans(
            usable, metadata.capture_times, config.dest.root, subdir=config.dest.subdir,
            ledger_has_record=lambda relative: relative.as_posix() in ledger,
        )
    except NamingError as exc:
        raise OperationalError("cannot safely create import plan: {0}".format(exc))
    for plan in plans:
        if plan.collision_detected and plan.action is PlannedAction.COPY:
            warnings += 1
            logger.warning("Name collision has different content; preserving both as: %s", plan.relative_destination.as_posix())
    return plans, warnings, failures


def _print_plan(logger: logging.Logger, plans: Iterable[TransferPlan]) -> None:
    for plan in plans:
        logger.info("PLAN %s %s -> %s", plan.action.value, plan.source.path, plan.relative_destination.as_posix())


def _record_for(plan: TransferPlan, digest: str):
    return make_record(plan.relative_destination.as_posix(), digest, plan.source.size, plan.capture_time.value)


def _verify_records(root: Path, plans: Sequence[TransferPlan], ledger: Dict[str, LedgerRecord], logger: logging.Logger) -> bool:
    """Confirm every planned final file and its ledger entry after processing."""
    complete = True
    for plan in plans:
        key = plan.relative_destination.as_posix()
        record = ledger.get(key)
        if record is None:
            logger.error("Missing checksum record: %s", key)
            complete = False
            continue
        try:
            if plan.destination.stat().st_size != plan.source.size:
                raise OSError("size differs from source")
            source_digest = sha256_file(plan.source.path)
            destination_digest = sha256_file(plan.destination)
        except (OSError, NamingError) as exc:
            logger.error("Cannot recheck %s: %s", key, exc)
            complete = False
            continue
        if record.size != plan.source.size or record.digest != source_digest or destination_digest != source_digest:
            logger.error("Final checksum recheck failed: %s", key)
            complete = False
    return complete


def _transfer_with_replan(plan: TransferPlan, config: Config, ledger: Dict[str, LedgerRecord], resources: RunResources, logger: logging.Logger) -> Tuple[TransferPlan, TransferResult]:
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
            )[0]
        except (NamingError, IndexError) as exc:
            return current, TransferResult(TransferStatus.FAILED, current.source.path, current.destination, message="cannot safely replan conflict: {0}".format(exc))
    return current, TransferResult(TransferStatus.FAILED, current.source.path, current.destination, message="too many concurrent destination conflicts")


def import_handler(args: object, resources: RunResources, logger: logging.Logger) -> int:
    """Run the Phase-6 sequence, preserving the source card in all outcomes."""
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
        plans, warnings, failures = _build_plans(config, source, ledger, logger)
        _print_plan(logger, plans)
        try:
            ensure_capacity(config.dest.root, sum(plan.source.size for plan in plans if plan.action is PlannedAction.COPY), config.free_space_margin)
        except UsageError as exc:
            logger.error("%s", exc)
            return 1
        summary = ImportSummary(skipped=sum(p.action is PlannedAction.SKIP for p in plans), warnings=warnings,
                                failures=failures, dry_run=True)
        logger.info("DRY-RUN summary: copy %d / skip %d / warning %d / failure %d; no state was changed",
                    sum(p.action is PlannedAction.COPY for p in plans), summary.skipped, warnings, failures)
        return 1 if failures else 0

    # Every operation below this point may modify only the verified archive.
    # The lock precedes ledger repair, temporary-file recovery, and planning.
    acquire_lock(config.dest.root, exclusive=True, resources=resources)
    try:
        ledger = load_ledger(config.dest.root, repair_tail=True, log_dir=_log_directory(logger))
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
    ensure_writable(config.dest.root)
    ensure_hard_links(config.dest.root)
    # Replan after lock/repair; this is the authoritative execution plan.
    plans, warnings, failures = _build_plans(config, source, ledger, logger)
    _print_plan(logger, plans)
    try:
        ensure_capacity(config.dest.root, sum(p.source.size for p in plans if p.action is PlannedAction.COPY), config.free_space_margin)
    except UsageError as exc:
        logger.error("%s", exc)
        return 1

    copied = skipped = 0
    final_plans: List[TransferPlan] = []
    for plan in plans:
        current = plan
        if plan.action is PlannedAction.SKIP:
            try:
                if plan.ledger_missing:
                    supplement_record(config.dest.root, relative_path=plan.relative_destination.as_posix(), source_path=plan.source.path,
                                      captured_at=plan.capture_time.value)
                skipped += 1
                logger.info("SKIPPED verified duplicate: %s", plan.relative_destination.as_posix())
                final_plans.append(plan)
            except LedgerError as exc:
                failures += 1
                logger.error("FAILED to supplement checksum for %s: %s", plan.relative_destination, exc)
            continue
        current, result = _transfer_with_replan(plan, config, ledger, resources, logger)
        if result.status is TransferStatus.COPIED:
            try:
                assert result.digest is not None
                append_record(config.dest.root, _record_for(current, result.digest))
                ledger[current.relative_destination.as_posix()] = _record_for(current, result.digest)
                copied += 1
                logger.info("COPIED and verified: %s -> %s", current.source.path, current.relative_destination.as_posix())
                final_plans.append(current)
            except LedgerError as exc:
                failures += 1
                logger.error("FAILED to record checksum for %s: %s", current.relative_destination, exc)
        elif result.status is TransferStatus.SKIPPED:
            try:
                if current.ledger_missing:
                    supplement_record(config.dest.root, relative_path=current.relative_destination.as_posix(), source_path=current.source.path,
                                      captured_at=current.capture_time.value)
                skipped += 1
                logger.info("SKIPPED verified duplicate after replan: %s", current.relative_destination.as_posix())
                final_plans.append(current)
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
        ledger_complete = failures == 0 and len(final_plans) == len(plans) and _verify_records(config.dest.root, final_plans, final_ledger, logger)
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
