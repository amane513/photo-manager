"""Read-only discovery of importable files on a camera card.

Only the four paths documented in ``requirements.md`` are ever returned.
In particular this module has no filesystem mutation calls: an SD card is an
input, not a workspace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


class SourceKind(str, Enum):
    STILL = "still"
    VIDEO = "video"
    SIDECAR_XML = "sidecar_xml"


@dataclass(frozen=True)
class SourceFile:
    path: Path
    kind: SourceKind
    size: int
    mtime: float
    paired_path: Optional[Path] = None


@dataclass(frozen=True)
class DiscoveryIssue:
    path: Path
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    files: Tuple[SourceFile, ...]
    failures: Tuple[DiscoveryIssue, ...]


def _is_apple_double(path: Path) -> bool:
    return path.name.startswith("._")


def _source_file(path: Path, kind: SourceKind, paired_path: Optional[Path] = None) -> SourceFile:
    stat = path.stat()
    return SourceFile(path=path, kind=kind, size=stat.st_size, mtime=stat.st_mtime, paired_path=paired_path)


def _children_named(parent: Path, wanted: str) -> List[Path]:
    """Find direct children by a case-insensitive camera-media name."""
    if not parent.is_dir():
        return []
    return [child for child in parent.iterdir() if child.name.casefold() == wanted.casefold()]


def _walk_regular(directory: Path) -> Iterable[Path]:
    # os.walk does not follow directory symlinks.  This avoids letting a card
    # entry make discovery escape the mounted card root.
    for root, directories, names in os.walk(str(directory), followlinks=False):
        directories[:] = [name for name in directories if not name.startswith("._")]
        for name in names:
            if name.startswith("._"):
                continue
            path = Path(root) / name
            if path.is_file() and not path.is_symlink():
                yield path


def discover_files(source_root: Path) -> DiscoveryResult:
    """Enumerate permitted source files and report unplannable XML pairings.

    Matching is case-insensitive to match exFAT camera media, while the actual
    ``Path`` (and therefore original filename casing) is retained unchanged.
    """
    root = source_root.absolute()
    found: List[SourceFile] = []
    failures: List[DiscoveryIssue] = []

    for dcim in _children_named(root, "DCIM"):
        if not dcim.is_dir():
            continue
        for path in _walk_regular(dcim):
            suffix = path.suffix.casefold()
            if suffix == ".jpg" or suffix == ".arw":
                found.append(_source_file(path, SourceKind.STILL))

    clips: List[Path] = []
    for private in _children_named(root, "PRIVATE"):
        for m4root in _children_named(private, "M4ROOT"):
            clips.extend(_children_named(m4root, "CLIP"))
    # Multiple differently-cased camera directories should not normally exist,
    # but retaining both makes ambiguity fail safely rather than silently pick.
    video_paths: List[Path] = []
    xml_paths: List[Path] = []
    for clip in clips:
        if not clip.is_dir():
            continue
        for path in clip.iterdir():
            if _is_apple_double(path) or not path.is_file() or path.is_symlink():
                continue
            if path.suffix.casefold() == ".mp4":
                video_paths.append(path)
            elif path.suffix.casefold() == ".xml":
                xml_paths.append(path)

    xml_by_parent_and_name: Dict[Tuple[Path, str], List[Path]] = {}
    for xml in xml_paths:
        xml_by_parent_and_name.setdefault((xml.parent, xml.name.casefold()), []).append(xml)
    paired_xmls = set()
    rejected_videos = set()
    for video in video_paths:
        expected = video.stem.casefold() + "m01.xml"
        candidates = xml_by_parent_and_name.get((video.parent, expected), [])
        if len(candidates) > 1:
            rejected_videos.add(video)
            failures.append(DiscoveryIssue(video, "multiple sidecar XML files match this MP4"))
            for candidate in candidates:
                failures.append(DiscoveryIssue(candidate, "ambiguous sidecar XML; MP4 was not planned"))
        elif candidates:
            xml = candidates[0]
            paired_xmls.add(xml)
            found.append(_source_file(video, SourceKind.VIDEO, xml))
            found.append(_source_file(xml, SourceKind.SIDECAR_XML, video))
        else:
            found.append(_source_file(video, SourceKind.VIDEO))
    for xml in xml_paths:
        if xml not in paired_xmls:
            # Ambiguous XMLs are already reported above; avoid duplicate noise.
            if not any(issue.path == xml for issue in failures):
                failures.append(DiscoveryIssue(xml, "orphan sidecar XML has no matching MP4"))

    # A deterministic plan is essential for dry-run/output tests.  This sort
    # changes neither source names nor the card.
    found.sort(key=lambda item: str(item.path))
    return DiscoveryResult(tuple(found), tuple(failures))
