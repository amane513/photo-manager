"""Read-only destination naming and collision planning.

This module deliberately only inspects source and archive files.  It never
creates, replaces, unlinks, or otherwise mutates either tree; in particular a
camera card is only opened for reading while comparing a duplicate.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .discovery import SourceFile
from .metadata import CaptureTime


class PlannedAction(str, Enum):
    """What a later transfer phase should do with a planned source file."""

    COPY = "copy"
    SKIP = "skip"


class NamingError(ValueError):
    """A destination cannot safely be used for a transfer plan."""


@dataclass(frozen=True)
class TransferPlan:
    """A fully resolved, but not yet executed, archive operation.

    ``ledger_missing`` is meaningful only for a skipped file.  It tells the
    ledger phase that the already-existing archive file was verified against
    the source and can therefore have its missing record safely backfilled.
    """

    source: SourceFile
    capture_time: CaptureTime
    destination: Path
    relative_destination: Path
    action: PlannedAction
    collision_detected: bool
    ledger_missing: bool = False

    @property
    def target_path(self) -> Path:
        """Compatibility-friendly descriptive name for ``destination``."""
        return self.destination

    @property
    def needs_ledger_record(self) -> bool:
        return self.ledger_missing


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return a SHA-256 digest while reading one file, without modifying it."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise NamingError("cannot hash {0}: {1}".format(path, exc))
    return digest.hexdigest()


def archive_relative_path(capture_time: CaptureTime, original_name: str, *, subdir: str = "Camera") -> Path:
    """Make the specified ``Camera/YYYY/YYYY-MM/prefixed-original`` path.

    ``strftime`` is intentionally applied directly to the capture datetime:
    aware timestamps retain their recorded local wall-clock date rather than
    being converted to the import machine's timezone.
    """
    if not original_name or original_name in (".", "..") or "/" in original_name:
        raise NamingError("source filename is not a safe filename: {0!r}".format(original_name))
    subdirectory = Path(subdir)
    if subdirectory.is_absolute() or ".." in subdirectory.parts or str(subdirectory) in ("", "."):
        raise NamingError("archive subdir must be a non-empty relative path")
    value = capture_time.value
    prefix = value.strftime("%Y%m%d_%H%M%S_")
    year = value.strftime("%Y")
    month = value.strftime("%Y-%m")
    return subdirectory / year / month / (prefix + original_name)


def _numbered_name(name: str, number: int) -> str:
    """Place ``_N`` immediately before the original extension, preserving it."""
    if number < 2:
        raise ValueError("collision numbers start at 2")
    suffix = Path(name).suffix
    if suffix:
        return name[:-len(suffix)] + "_" + str(number) + suffix
    return name + "_" + str(number)


def _existing_regular_file(path: Path) -> bool:
    """Return whether candidate is absent/regular; reject unsafe occupants."""
    try:
        value = os.lstat(str(path))
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise NamingError("cannot inspect destination {0}: {1}".format(path, exc))
    if not stat.S_ISREG(value.st_mode):
        raise NamingError("destination candidate is not a regular file: {0}".format(path))
    return True


def _same_content(source: SourceFile, candidate: Path, source_digests: Dict[Path, str]) -> bool:
    """Fast size check followed by SHA-256, as required for every candidate."""
    try:
        if candidate.stat().st_size != source.size:
            return False
    except OSError as exc:
        raise NamingError("cannot stat destination {0}: {1}".format(candidate, exc))
    source_digest = source_digests.get(source.path)
    if source_digest is None:
        source_digest = sha256_file(source.path)
        source_digests[source.path] = source_digest
    return source_digest == sha256_file(candidate)


def build_transfer_plans(
    files: Sequence[SourceFile],
    capture_times: Mapping[Path, CaptureTime],
    destination_root: Path,
    *,
    subdir: str = "Camera",
    ledger_paths: Optional[Iterable[Path]] = None,
    ledger_has_record: Optional[Callable[[Path], bool]] = None,
) -> Tuple[TransferPlan, ...]:
    """Resolve deterministic safe destinations without writing anywhere.

    A matching existing candidate is skipped.  A differing occupant is never
    overwritten: numbered candidates are examined in sequence, each using the
    same size-then-hash comparison, until an absent path is found.  ``ledger``
    input is optional because its parser belongs to Phase 5; callers that
    provide it receive the precise backfill flag for skipped files.
    """
    if ledger_paths is not None and ledger_has_record is not None:
        raise ValueError("provide ledger_paths or ledger_has_record, not both")
    root = destination_root.absolute()
    known_ledger_paths = set(ledger_paths) if ledger_paths is not None else None
    source_digests: Dict[Path, str] = {}
    plans = []

    # The order does not alter individual names, but makes dry-run output and
    # tests deterministic.  XML's inherited CaptureTime gives it its MP4's
    # prefix, so lexical ordering keeps the pair adjacent.
    ordered = sorted(files, key=lambda item: str(item.path))
    for source in ordered:
        capture = capture_times.get(source.path)
        if capture is None:
            raise NamingError("no capture time for source file: {0}".format(source.path))
        relative = archive_relative_path(capture, source.path.name, subdir=subdir)
        base_name = relative.name
        candidate = root / relative
        collision = False
        number = 1
        while _existing_regular_file(candidate):
            collision = True
            if _same_content(source, candidate, source_digests):
                if ledger_has_record is not None:
                    missing = not ledger_has_record(relative)
                elif known_ledger_paths is not None:
                    missing = relative not in known_ledger_paths
                else:
                    missing = False
                plans.append(TransferPlan(source, capture, candidate, relative, PlannedAction.SKIP, collision, missing))
                break
            number += 1
            candidate = candidate.with_name(_numbered_name(base_name, number))
            relative = relative.with_name(candidate.name)
        else:
            plans.append(TransferPlan(source, capture, candidate, relative, PlannedAction.COPY, collision))
    return tuple(plans)


# A concise alias for callers that prefer the Phase-3 vocabulary.
plan_transfers = build_transfer_plans
