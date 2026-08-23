"""Mounted-volume checks.  None of these functions write to a source volume."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import uuid
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from .runtime import UsageError
from .runtime import OperationalError


@dataclass(frozen=True)
class VolumeInfo:
    mount_point: Path
    volume_uuid: str
    device_identifier: str
    parent_whole_disk: str


Runner = Callable[..., subprocess.CompletedProcess]


def volume_info(path: Path, *, runner: Runner = subprocess.run, diskutil: str = "/usr/sbin/diskutil") -> VolumeInfo:
    root = path.expanduser()
    if not root.is_dir():
        raise UsageError("volume is not mounted: {0}".format(root))
    try:
        result = runner([diskutil, "info", "-plist", str(root)], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise UsageError("cannot inspect volume {0}: {1}".format(root, exc))
    if result.returncode != 0:
        raise UsageError("cannot inspect volume: {0}".format(root))
    try:
        data = plistlib.loads(result.stdout)
        mount = Path(data["MountPoint"])
        identifier = str(data["DeviceIdentifier"])
        parent = str(data["ParentWholeDisk"])
        volume_uuid = str(data["VolumeUUID"])
    except (KeyError, TypeError, ValueError, plistlib.InvalidFileException) as exc:
        raise UsageError("invalid diskutil information for {0}: {1}".format(root, exc))
    if mount.resolve() != root.resolve():
        raise UsageError("volume mount point changed while checking: {0}".format(root))
    return VolumeInfo(mount, volume_uuid, identifier, parent)


def validate_volume(path: Path, expected_uuid: str, **kwargs: object) -> VolumeInfo:
    info = volume_info(path, **kwargs)
    if info.volume_uuid.casefold() != expected_uuid.casefold():
        raise UsageError("volume UUID mismatch for {0}: expected {1}, got {2}".format(path, expected_uuid, info.volume_uuid))
    return info


def _discard_probe(path: Path) -> None:
    """Best-effort removal of a probe file this process just created."""
    try:
        path.unlink()
    except OSError:
        # Never mask the failure or interruption which is already unwinding.
        pass


def _discard_probe_directory(directory: Path) -> None:
    """Remove a directory only if this process created it and it is empty."""
    try:
        directory.rmdir()
    except OSError:
        # A concurrent run may already own content here; leave it alone.
        pass


def ensure_writable(destination: Path) -> None:
    """Perform a real exclusive create/unlink probe on the destination only."""
    probe = destination / ".photo-manager-write-probe-{0}".format(uuid.uuid4().hex)
    try:
        fd = os.open(str(probe), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise UsageError("destination is not writable: {0}: {1}".format(destination, exc))
    try:
        os.close(fd)
    except OSError as exc:
        _discard_probe(probe)
        raise UsageError("destination is not writable: {0}: {1}".format(destination, exc))
    except BaseException:
        # Includes RunInterrupted: the probe file this call created must not
        # survive a failed or interrupted preflight.
        _discard_probe(probe)
        raise
    try:
        probe.unlink()
    except OSError as exc:
        raise UsageError("destination write probe could not be cleaned up: {0}".format(exc))


def ensure_exiftool(exiftool: Path) -> None:
    """Require the configured absolute executable without invoking it yet."""
    if not exiftool.is_absolute() or not exiftool.is_file() or not os.access(str(exiftool), os.X_OK):
        raise UsageError("configured exiftool is not executable: {0}".format(exiftool))


def ensure_hard_links(destination: Path) -> None:
    """Verify the exact primitive used for safe finalisation, leaving no files.

    This runs before the destination lock is taken, so it must be invisible in
    every outcome: success, failure and interruption all remove the probe files
    and any directory this call itself created.  Directories which already
    existed are never removed; they may hold another process's lock or a
    previous run's recovery data.
    """
    management = destination / "_photo-manager"
    tmp = management / "tmp"
    made_management = not management.exists()
    made_tmp = not tmp.exists()
    try:
        tmp.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UsageError("cannot create destination management directory: {0}".format(exc))
    source = tmp / ".hard-link-probe-{0}".format(uuid.uuid4().hex)
    linked = tmp / ".hard-link-probe-link-{0}".format(uuid.uuid4().hex)
    try:
        try:
            fd = os.open(str(source), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            raise UsageError("destination does not support required hard links: {0}".format(exc))
        try:
            os.close(fd)
            os.link(str(source), str(linked))
        except OSError as exc:
            raise UsageError("destination does not support required hard links: {0}".format(exc))
    finally:
        # Runs for success, UsageError and interruption alike.
        for candidate in (linked, source):
            _discard_probe(candidate)
        if made_tmp:
            _discard_probe_directory(tmp)
        if made_management:
            _discard_probe_directory(management)


def ensure_capacity(destination: Path, required_bytes: int, margin: float) -> None:
    if required_bytes < 0:
        raise ValueError("required_bytes must not be negative")
    available = shutil.disk_usage(str(destination)).free
    needed = int(math.ceil(required_bytes * margin))
    if available < needed:
        raise UsageError("insufficient destination space: need {0} bytes, have {1}".format(needed, available))


def is_source_candidate(path: Path) -> bool:
    return path.is_dir() and ((path / "DCIM").is_dir() or (path / "PRIVATE" / "M4ROOT").is_dir())


def discover_source(destination: Path, *, volumes_root: Path = Path("/Volumes")) -> Path:
    """Find exactly one eligible mounted card; never create or alter candidates."""
    try:
        destination_id = destination.resolve()
        candidates = [entry for entry in volumes_root.iterdir() if entry.resolve() != destination_id and is_source_candidate(entry)]
    except OSError as exc:
        raise UsageError("cannot inspect mounted volumes: {0}".format(exc))
    if len(candidates) != 1:
        rendered = ", ".join(str(path) for path in candidates) or "none"
        raise UsageError("expected exactly one SD-card source candidate; found: {0}".format(rendered))
    return candidates[0]


def validate_source(source: Path, *, destination: Optional[Path] = None) -> Path:
    root = source.expanduser()
    if not is_source_candidate(root):
        raise UsageError("source does not contain DCIM or PRIVATE/M4ROOT: {0}".format(root))
    if destination is not None:
        try:
            if root.resolve() == destination.expanduser().resolve():
                raise UsageError("source and destination must be different volumes")
        except OSError as exc:
            raise UsageError("cannot compare source and destination: {0}".format(exc))
    return root


def eject_volume(source: Path, *, runner: Runner = subprocess.run, diskutil: str = "/usr/sbin/diskutil") -> None:
    """Eject the verified whole disk, never a partition identifier.

    The immediately preceding ``diskutil info`` rereads the mount point and
    captures ``ParentWholeDisk`` from the same authoritative plist.  No files
    on the card are opened for writing or removed.
    """
    before = source.expanduser().resolve()
    try:
        info = volume_info(source, runner=runner, diskutil=diskutil)
    except UsageError as exc:
        raise OperationalError("cannot safely recheck source before eject: {0}".format(exc))
    if info.mount_point.resolve() != before:
        raise OperationalError("source mount point changed before eject")
    try:
        result = runner([diskutil, "eject", info.parent_whole_disk], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise OperationalError("could not eject SD card: {0}".format(exc))
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise OperationalError("diskutil eject failed for {0}: {1}".format(info.parent_whole_disk, detail))
