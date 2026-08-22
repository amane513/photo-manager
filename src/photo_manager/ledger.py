"""Append-only, validated checksum ledger for an archive destination.

This module only ever writes the destination's ``_photo-manager`` directory.
It has no operation which opens, removes, or otherwise changes a source-card
file.  In particular, repair is deliberately restricted to ``checksums.tsv``
and first saves the original in the supplied host log directory.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional

from .runtime import OperationalError


LEDGER_DIRECTORY = "_photo-manager"
LEDGER_FILENAME = "checksums.tsv"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INTEGER = re.compile(r"^(0|[1-9][0-9]*)$")


class LedgerError(OperationalError):
    """The ledger is invalid or could not be safely changed."""


@dataclass(frozen=True)
class LedgerRecord:
    """One canonical six-field entry in ``checksums.tsv``."""

    path: str
    algorithm: str
    digest: str
    size: int
    captured_at: str
    imported_at: str

    def fields(self) -> List[str]:
        return [self.path, self.algorithm, self.digest, str(self.size), self.captured_at, self.imported_at]


def ledger_path(destination_root: Path) -> Path:
    """Return the only ledger path this module is permitted to modify."""
    return destination_root.absolute() / LEDGER_DIRECTORY / LEDGER_FILENAME


def _full_sync(fd: int) -> None:
    command = getattr(fcntl, "F_FULLFSYNC", None)
    if command is not None:
        try:
            fcntl.fcntl(fd, command)
            return
        except OSError:
            pass
    os.fsync(fd)


def _sync_directory(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        _full_sync(fd)
    finally:
        os.close(fd)


def _parse_iso(value: str, *, require_offset: bool, field: str) -> None:
    # fromisoformat is available on all supported Python versions.  Requiring
    # round-trip equality fixes the on-disk form (no fractions, no "Z", and
    # no alternate separators) rather than merely accepting a broad family.
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise LedgerError("invalid {0} timestamp: {1!r}".format(field, value))
    if parsed.isoformat(timespec="seconds") != value:
        raise LedgerError("{0} must be ISO 8601 with second precision: {1!r}".format(field, value))
    if require_offset and (parsed.tzinfo is None or parsed.utcoffset() is None):
        raise LedgerError("{0} must include a numeric UTC offset: {1!r}".format(field, value))


def _validate_relative_path(value: str) -> None:
    if not value or "\\" in value or value.startswith("/"):
        raise LedgerError("ledger path is not a relative POSIX path: {0!r}".format(value))
    path = PurePosixPath(value)
    if str(path) != value or any(part in ("", ".", "..") for part in path.parts):
        raise LedgerError("ledger path is not normalized: {0!r}".format(value))
    if path.parts[0] == LEDGER_DIRECTORY:
        raise LedgerError("ledger path must not point into the management directory: {0!r}".format(value))


def validate_record(fields: List[str]) -> LedgerRecord:
    """Validate exactly one raw TSV row and return its canonical record."""
    if len(fields) != 6:
        raise LedgerError("ledger row must have exactly 6 columns (has {0})".format(len(fields)))
    path, algorithm, digest, size_text, captured_at, imported_at = fields
    _validate_relative_path(path)
    if algorithm != "sha256":
        raise LedgerError("unsupported ledger algorithm: {0!r}".format(algorithm))
    if not _HEX_SHA256.fullmatch(digest):
        raise LedgerError("sha256 digest must be 64 lowercase hexadecimal characters")
    if not _INTEGER.fullmatch(size_text):
        raise LedgerError("ledger size must be a non-negative canonical integer: {0!r}".format(size_text))
    _parse_iso(captured_at, require_offset=False, field="captured_at")
    _parse_iso(imported_at, require_offset=True, field="imported_at")
    return LedgerRecord(path, algorithm, digest, int(size_text), captured_at, imported_at)


def make_record(path: str, digest: str, size: int, captured_at: datetime, imported_at: Optional[datetime] = None) -> LedgerRecord:
    """Create a canonical record; imported time is always offset-aware."""
    if imported_at is None:
        imported_at = datetime.now().astimezone()
    record = LedgerRecord(
        path=path,
        algorithm="sha256",
        digest=digest,
        size=size,
        captured_at=captured_at.isoformat(timespec="seconds"),
        imported_at=imported_at.isoformat(timespec="seconds"),
    )
    return validate_record(record.fields())


def _read_rows(raw: bytes) -> List[List[str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LedgerError("ledger is not UTF-8: {0}".format(exc))
    try:
        return list(csv.reader(io.StringIO(text, newline=""), dialect="excel-tab", strict=True))
    except csv.Error as exc:
        raise LedgerError("malformed TSV quoting: {0}".format(exc))


def _records_from_raw(raw: bytes) -> List[LedgerRecord]:
    records: List[LedgerRecord] = []
    seen = set()
    for number, fields in enumerate(_read_rows(raw), 1):
        try:
            record = validate_record(fields)
        except LedgerError as exc:
            raise LedgerError("invalid ledger row {0}: {1}".format(number, exc))
        if record.path in seen:
            raise LedgerError("duplicate ledger path at row {0}: {1!r}".format(number, record.path))
        seen.add(record.path)
        records.append(record)
    return records


def _serialize(records: Iterable[LedgerRecord]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, dialect="excel-tab", lineterminator="\n")
    for record in records:
        writer.writerow(record.fields())
    return buffer.getvalue().encode("utf-8")


def _backup_original(path: Path, log_dir: Path) -> Path:
    """Copy and fsync the old ledger using an exclusive log filename."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    for index in range(1, 10000):
        suffix = "" if index == 1 else "-{0}".format(index)
        backup = log_dir / "checksums.tsv.corrupt-{0}{1}".format(stamp, suffix)
        try:
            source_fd = os.open(str(path), os.O_RDONLY)
            try:
                target_fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    while True:
                        block = os.read(source_fd, 1024 * 1024)
                        if not block:
                            break
                        os.write(target_fd, block)
                    _full_sync(target_fd)
                finally:
                    os.close(target_fd)
            finally:
                os.close(source_fd)
            _sync_directory(log_dir)
            return backup
        except FileExistsError:
            continue
        except OSError as exc:
            raise LedgerError("could not back up corrupt ledger before repair: {0}".format(exc))
    raise LedgerError("could not allocate corrupt ledger backup filename")


def _replace_records(path: Path, records: Iterable[LedgerRecord]) -> None:
    """Atomically replace only the management ledger after a safe backup."""
    temporary = path.with_name(path.name + ".repair.part")
    try:
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise LedgerError("refusing repair: managed repair temporary already exists")
    try:
        data = _serialize(records)
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        _full_sync(fd)
    except OSError as exc:
        try:
            os.close(fd)
        finally:
            # It is a freshly O_EXCL-created management temporary, so this is
            # the sole permitted cleanup unlink in this module.
            temporary.unlink()
        raise LedgerError("could not write repaired ledger: {0}".format(exc))
    else:
        os.close(fd)
    try:
        os.replace(str(temporary), str(path))
        _sync_directory(path.parent)
    except OSError as exc:
        # Do not unlink after a possibly-successful replace.  The replacement
        # affects only the management file and the backup remains available.
        raise LedgerError("could not atomically install repaired ledger: {0}".format(exc))


def replace_ledger(destination_root: Path, records: Iterable[LedgerRecord]) -> None:
    """Atomically install a complete, already-validated ledger snapshot.

    This is intentionally separate from :func:`append_record`: mirroring must
    never publish a partially copied ledger.  The temporary is private to the
    destination management directory, is fsynced, parsed again, and only then
    replaces ``checksums.tsv``.  No archive data file is removed or replaced.
    """
    checked = [validate_record(record.fields()) for record in records]
    seen = set()
    for record in checked:
        if record.path in seen:
            raise LedgerError("duplicate ledger path in replacement: {0!r}".format(record.path))
        seen.add(record.path)
    path = ledger_path(destination_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LedgerError("could not create ledger directory: {0}".format(exc))
    temporary = path.with_name(path.name + ".mirror.part")
    try:
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise LedgerError("refusing mirror ledger update: managed temporary already exists")
    try:
        data = _serialize(checked)
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        _full_sync(fd)
    except OSError as exc:
        try:
            os.close(fd)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise LedgerError("could not write mirror ledger temporary: {0}".format(exc))
    else:
        os.close(fd)
    try:
        # Parse the durable temporary itself; serialization bugs cannot turn
        # into a published checksum ledger.
        _records_from_raw(temporary.read_bytes())
        os.replace(str(temporary), str(path))
        _sync_directory(path.parent)
    except (OSError, LedgerError) as exc:
        # Do not unlink after os.replace might have succeeded.  A leftover
        # private temporary is safer than guessing which file is authoritative.
        raise LedgerError("could not atomically install mirror ledger: {0}".format(exc))


def load_ledger(destination_root: Path, *, repair_tail: bool = False, log_dir: Optional[Path] = None) -> Dict[str, LedgerRecord]:
    """Read and strictly validate the ledger, optionally repairing a bad tail.

    Only an invalid *unterminated final physical row* is repairable.  Every
    other syntax/semantic error, including a bad row in the middle, fails with
    no modification.  ``log_dir`` is mandatory for repair because a durable
    original backup is a precondition to changing the management file.
    """
    path = ledger_path(destination_root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise LedgerError("could not read ledger: {0}".format(exc))
    try:
        records = _records_from_raw(raw)
    except LedgerError as original_error:
        # A partial CSV field is only accepted as a tail if bytes after the
        # final LF constitute the failed final row.  This intentionally does
        # not repair an invalid newline-terminated row or a middle corruption.
        if not repair_tail or log_dir is None or raw.endswith(b"\n") or b"\n" not in raw:
            raise original_error
        prefix = raw.rsplit(b"\n", 1)[0] + b"\n"
        try:
            complete = _records_from_raw(prefix)
        except LedgerError:
            raise original_error
        _backup_original(path, log_dir)
        _replace_records(path, complete)
        records = complete
    return {record.path: record for record in records}


def append_record(destination_root: Path, record: LedgerRecord) -> bool:
    """Durably append a new record after validation.

    Returns ``False`` for a byte-for-byte equivalent existing entry.  A record
    for the same path but different contents is an error: changing history
    would conceal an existing archive conflict.
    """
    record = validate_record(record.fields())
    existing = load_ledger(destination_root)
    prior = existing.get(record.path)
    if prior is not None:
        if prior == record:
            return False
        # Imported-at may differ when recovering an interrupted import; same
        # data is still the same logical record and must not be duplicated.
        if (prior.algorithm, prior.digest, prior.size) == (record.algorithm, record.digest, record.size):
            return False
        raise LedgerError("ledger already contains a different record for {0!r}".format(record.path))
    path = ledger_path(destination_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            data = _serialize([record])
            offset = 0
            while offset < len(data):
                offset += os.write(fd, data[offset:])
            _full_sync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise LedgerError("could not append ledger record: {0}".format(exc))
    return True


def supplement_record(destination_root: Path, *, relative_path: str, source_path: Path, captured_at: datetime, imported_at: Optional[datetime] = None) -> bool:
    """Add an absent entry only after source and destination independently match.

    This is the interrupted-import recovery path.  Both files are read; it
    never assumes a destination hash is trustworthy merely because a source
    file has gone away.
    """
    _validate_relative_path(relative_path)
    destination = destination_root.absolute() / Path(*PurePosixPath(relative_path).parts)
    try:
        destination.relative_to(destination_root.absolute())
    except ValueError:
        raise LedgerError("supplement path escapes destination root")
    try:
        source_size = source_path.stat().st_size
        destination_size = destination.stat().st_size
    except OSError as exc:
        raise LedgerError("could not inspect files for ledger supplement: {0}".format(exc))
    if source_size != destination_size:
        raise LedgerError("source and destination sizes differ; ledger is not supplemented")
    def digest_file(file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    try:
        source_digest = digest_file(source_path)
        destination_digest = digest_file(destination)
    except OSError as exc:
        raise LedgerError("could not hash files for ledger supplement: {0}".format(exc))
    if source_digest != destination_digest:
        raise LedgerError("source and destination hashes differ; ledger is not supplemented")
    return append_record(destination_root, make_record(relative_path, source_digest, source_size, captured_at, imported_at))
