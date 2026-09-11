"""対象列挙、組ファイル判定、配置計画の共通API。"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

from .metadata import MetadataError, capture_timestamp
from .models import CopyRequest, ItemStatus, PlannedItem


SUPPORTED_SUFFIXES = frozenset({".arw", ".jpg", ".jpeg", ".heic", ".mov", ".mp4", ".xmp"})
YEAR_MONTH_PATTERN = re.compile(r"^([0-9]{4})-([0-9]{2})$")
TIMESTAMP_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}$")


def enumerate_files(source: Path) -> tuple[Path, ...]:
    """コピー元配下の通常ファイルを、安定した順で列挙する。"""

    if not source.is_dir():
        raise ValueError(f"コピー元ディレクトリが存在しない: {source}")
    return tuple(sorted((path for path in source.rglob("*") if path.is_file()), key=lambda path: str(path)))


def _base_name(path: Path) -> str:
    """ARWのXMPをARW/JPEGと対応させるための撮影名を返す。"""

    name = path.name
    if name.lower().endswith(".arw.xmp"):
        return name[: -len(".arw.xmp")]
    return path.stem


def group_key(source_root: Path, path: Path) -> str:
    """同一ディレクトリ内だけで組ファイルを対応付けるキーを返す。"""

    return str(path.relative_to(source_root).parent / _base_name(path)).lower()


def _members_by_key(source_root: Path, paths: Iterable[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in paths:
        groups.setdefault(group_key(source_root, path), []).append(path)
    return groups


def _reference_member(members: list[Path]) -> Path | None:
    """SonyはARW、Live PhotoはHEICを組の日時基準にする。"""

    suffixes = {member.suffix.lower() for member in members}
    arw = next((member for member in members if member.suffix.lower() == ".arw"), None)
    if arw is not None:
        return arw
    if ".heic" in suffixes and ".mov" in suffixes:
        return next(member for member in members if member.suffix.lower() == ".heic")
    return None


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def _destination(request: CopyRequest, path: Path, timestamp: str) -> Path:
    year, month = _validated_year_month(request.year_month)
    return request.destination_root / year / f"{year}-{month}" / request.device.value / f"{timestamp}_{path.name}"


def _validated_year_month(value: str) -> tuple[str, str]:
    match = YEAR_MONTH_PATTERN.fullmatch(value)
    if match is None or not 1 <= int(match.group(2)) <= 12:
        raise ValueError("年月はYYYY-MM形式で指定する")
    return match.group(1), match.group(2)


def build_plan(
    request: CopyRequest,
    *,
    timestamp_for: Callable[[Path], str | None] = capture_timestamp,
) -> tuple[PlannedItem, ...]:
    """コピー元を変更せず、実行前に全ファイルの配置先を決める。

    基準ファイルを持つ組は、そのファイルの日時を全員に適用する。基準日時が
    取得できない組は全員を未処理にし、コピー元に残す。
    """

    _validated_year_month(request.year_month)
    files = enumerate_files(request.source)
    groups = _members_by_key(request.source, files)
    planned: list[PlannedItem] = []

    for key in sorted(groups):
        members = sorted(groups[key], key=lambda path: str(path))
        unsupported = [member for member in members if not _is_supported(member)]
        supported = [member for member in members if _is_supported(member)]
        for member in unsupported:
            planned.append(PlannedItem(member, None, None, key, ItemStatus.UNRESOLVED, "未対応の形式である"))
        if not supported:
            continue

        reference = _reference_member(supported)
        try:
            timestamp = timestamp_for(reference) if reference is not None else None
            if reference is None and len(supported) == 1:
                timestamp = timestamp_for(supported[0])
        except MetadataError as error:
            timestamp = None
            reason = str(error)
        else:
            reason = None

        if timestamp is None or TIMESTAMP_PATTERN.fullmatch(timestamp) is None:
            if reference is not None:
                reason = reason or "組の基準ファイルから撮影日時を取得できない"
            elif len(supported) > 1:
                reason = "組の基準ファイルがない"
            else:
                reason = reason or "撮影日時を取得できない"
            if timestamp is not None and TIMESTAMP_PATTERN.fullmatch(timestamp) is None:
                reason = "撮影日時の形式が不正である"
            for member in supported:
                planned.append(PlannedItem(member, None, None, key, ItemStatus.UNRESOLVED, reason))
            continue

        for member in supported:
            planned.append(PlannedItem(member, _destination(request, member, timestamp), timestamp, key, ItemStatus.PLANNED))

    return tuple(sorted(planned, key=lambda item: str(item.source)))
