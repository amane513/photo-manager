"""Capture-time extraction for read-only discovered camera files."""
from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .discovery import DiscoveryIssue, SourceFile, SourceKind


@dataclass(frozen=True)
class CaptureTime:
    value: datetime
    source: str
    warning: Optional[str] = None


@dataclass(frozen=True)
class MetadataResult:
    capture_times: Mapping[Path, CaptureTime]
    failures: Tuple[DiscoveryIssue, ...]
    warnings: Tuple[DiscoveryIssue, ...]


_EXIF_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y:%m:%d %H:%M:%S%z")


def _parse_exif_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in _EXIF_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _parse_timezone(value: object) -> Optional[timezone]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.upper().startswith("UTC"):
        text = text[3:]
    match = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", text)
    if not match:
        return None
    minutes = int(match.group(2)) * 60 + int(match.group(3))
    if minutes > 23 * 60 + 59:
        return None
    if match.group(1) == "-":
        minutes = -minutes
    return timezone(timedelta(minutes=minutes))


def _mtime(file: SourceFile) -> CaptureTime:
    # fromtimestamp deliberately produces a naive local wall-clock datetime;
    # this is the required treatment for an mtime fallback.
    return CaptureTime(datetime.fromtimestamp(file.mtime), "mtime")


def read_xml_creation_date(path: Path) -> Optional[datetime]:
    """Read the first CreationDate value, returning None for malformed/missing."""
    try:
        root = ElementTree.parse(str(path)).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "CreationDate":
            value = element.attrib.get("value")
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
    return None


def read_exiftool_json(exiftool: Path, files: Sequence[SourceFile], *, runner=subprocess.run) -> Mapping[Path, Mapping[str, object]]:
    """Read only required tags and strictly bind every JSON row to its input.

    ``SourceFile`` must exactly be one requested absolute pathname.  Missing,
    duplicate, unexpected, or non-object rows make planning unsafe and raise
    ``ValueError`` instead of accidentally assigning another file's metadata.
    """
    if not exiftool.is_absolute():
        raise ValueError("exiftool path must be absolute")
    if not files:
        return {}
    paths = [item.path.absolute() for item in files]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate paths requested from exiftool")
    command = [str(exiftool), "-json", "-DateTimeOriginal", "-CreateDate", "-TimeZone"] + [str(path) for path in paths]
    try:
        completed = runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError as exc:
        raise ValueError("could not execute exiftool: {0}".format(exc))
    if completed.returncode != 0:
        raise ValueError("exiftool failed: {0}".format(completed.stderr.decode("utf-8", "replace").strip()))
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("exiftool did not return JSON: {0}".format(exc))
    if not isinstance(payload, list) or len(payload) != len(paths):
        raise ValueError("exiftool returned an unexpected number of records")
    requested = {str(path): path for path in paths}
    records: Dict[Path, Mapping[str, object]] = {}
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("SourceFile"), str):
            raise ValueError("exiftool result is missing SourceFile")
        source = row["SourceFile"]
        if source not in requested or requested[source] in records:
            raise ValueError("exiftool SourceFile does not exactly match a requested path: {0}".format(source))
        records[requested[source]] = row
    if len(records) != len(requested):
        raise ValueError("exiftool omitted metadata for a requested path")
    return records


def determine_capture_times(files: Sequence[SourceFile], exiftool: Path, *, runner=subprocess.run) -> MetadataResult:
    """Apply the documented capture-time precedence without modifying sources."""
    media = [file for file in files if file.kind in (SourceKind.STILL, SourceKind.VIDEO)]
    try:
        tags = read_exiftool_json(exiftool, media, runner=runner)
    except ValueError as exc:
        # A malformed or mismatched JSON response is not equivalent to a
        # missing tag.  Refuse to plan it: otherwise one bad invocation could
        # silently route an entire card by mtime.  Per-file missing tags still
        # use their documented mtime fallback below.
        reason = "cannot safely read exiftool metadata: {0}".format(exc)
        affected = [DiscoveryIssue(file.path, reason) for file in files]
        return MetadataResult({}, tuple(affected), ())
    captures: Dict[Path, CaptureTime] = {}
    failures: List[DiscoveryIssue] = []
    warnings: List[DiscoveryIssue] = []
    for file in media:
        row = tags.get(file.path.absolute(), {})
        if file.kind == SourceKind.STILL:
            value = _parse_exif_datetime(row.get("DateTimeOriginal"))
            capture = CaptureTime(value, "exif:DateTimeOriginal") if value else _mtime(file)
        else:
            xml_value = read_xml_creation_date(file.paired_path) if file.paired_path else None
            if file.paired_path and xml_value is None:
                warnings.append(DiscoveryIssue(file.paired_path, "sidecar XML has no usable CreationDate; MP4 fallback used"))
            if xml_value is not None:
                capture = CaptureTime(xml_value, "xml:CreationDate")
            else:
                create = _parse_exif_datetime(row.get("CreateDate"))
                zone = _parse_timezone(row.get("TimeZone"))
                capture = CaptureTime(create.replace(tzinfo=zone), "quicktime:CreateDate+TimeZone") if create and zone else _mtime(file)
        captures[file.path] = capture
    for file in files:
        if file.kind != SourceKind.SIDECAR_XML:
            continue
        parent = captures.get(file.paired_path) if file.paired_path else None
        if parent is None:
            failures.append(DiscoveryIssue(file.path, "sidecar XML has no determined MP4 capture time"))
        else:
            captures[file.path] = CaptureTime(parent.value, "inherited:" + parent.source, parent.warning)
    return MetadataResult(captures, tuple(failures), tuple(warnings))
