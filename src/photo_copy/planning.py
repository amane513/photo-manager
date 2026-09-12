"""対象列挙、組ファイル判定、配置計画の共通API。"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from .metadata import MetadataError, capture_timestamp
from .models import CopyRequest, ItemStatus, Layout, PlannedItem


SUPPORTED_SUFFIXES = frozenset({".arw", ".jpg", ".jpeg", ".heic", ".mov", ".mp4", ".xmp"})
YEAR_MONTH_PATTERN = re.compile(r"^([0-9]{4})-([0-9]{2})$")
TIMESTAMP_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}$")

MISPLACED_CLASSIFY_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}_")
PRESERVE_DEVICE_NAMES = frozenset({"camera", "smartphone"})
YEAR_FOLDER_PATTERN = re.compile(r"^[0-9]{4}$")
YEAR_MONTH_FOLDER_PATTERN = re.compile(r"^([0-9]{4})-([0-9]{2})$")

OS_JUNK_FILE_NAMES = frozenset({".DS_Store", "Thumbs.db"})
OS_JUNK_DIR_NAMES = frozenset({".Spotlight-V100", ".Trashes", ".fseventsd"})


def _validate_only(only: Sequence[str]) -> None:
    for value in only:
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"--onlyは絶対パスや..を含まない相対パスで指定する: {value}")


def _validate_layout_arguments(request: CopyRequest) -> None:
    if request.layout is Layout.PRESERVE:
        if request.year_month is not None or request.device is not None:
            raise ValueError("layout=preserveでは--year-monthと--deviceを指定できない")
    else:
        if request.year_month is None or request.device is None:
            raise ValueError("layout=classifyでは--year-monthと--deviceが必須である")
        _validated_year_month(request.year_month)


def enumerate_files(source: Path, *, only: Sequence[str] = ()) -> tuple[Path, ...]:
    """コピー元配下の通常ファイルを、安定した順で列挙する。

    ``only`` を指定した場合は、コピー元からの相対パスがその部分木に含まれる
    ファイルだけを対象にする。
    """

    if not source.is_dir():
        raise ValueError(f"コピー元ディレクトリが存在しない: {source}")

    roots = tuple(Path(value) for value in only)
    files = (path for path in source.rglob("*") if path.is_file())
    if roots:
        files = (
            path
            for path in files
            if any(path.relative_to(source).is_relative_to(root) for root in roots)
        )
    return tuple(sorted(files, key=lambda path: str(path)))


def _is_os_junk(relative: Path) -> bool:
    """macOS・Windowsが作る雑多ファイルかどうかを、相対パスの各階層から判定する。"""

    if relative.name in OS_JUNK_FILE_NAMES or relative.name.startswith("._"):
        return True
    return bool(OS_JUNK_DIR_NAMES & set(relative.parts[:-1]))


def _split_os_junk(source: Path, files: Iterable[Path]) -> tuple[list[PlannedItem], list[Path]]:
    excluded: list[PlannedItem] = []
    remaining: list[Path] = []
    for path in files:
        relative = path.relative_to(source)
        if _is_os_junk(relative):
            excluded.append(PlannedItem(path, None, None, str(relative), ItemStatus.EXCLUDED, "OSが作る雑多ファイルである"))
        else:
            remaining.append(path)
    return excluded, remaining


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
    assert request.year_month is not None and request.device is not None
    year, month = _validated_year_month(request.year_month)
    return request.destination_root / year / f"{year}-{month}" / request.device.value / f"{timestamp}_{path.name}"


def _validated_year_month(value: str) -> tuple[str, str]:
    match = YEAR_MONTH_PATTERN.fullmatch(value)
    if match is None or not 1 <= int(match.group(2)) <= 12:
        raise ValueError("年月はYYYY-MM形式で指定する")
    return match.group(1), match.group(2)


def _build_classify_plan(
    request: CopyRequest,
    files: Iterable[Path],
    *,
    timestamp_for: Callable[[Path], str | None],
) -> list[PlannedItem]:
    """撮影日時を読み、組を判定して分類・改名する計画を作る。"""

    candidates: list[Path] = []
    planned: list[PlannedItem] = []
    for path in files:
        if MISPLACED_CLASSIFY_PATTERN.match(path.name):
            planned.append(
                PlannedItem(
                    path,
                    None,
                    None,
                    str(path.relative_to(request.source)),
                    ItemStatus.UNRESOLVED,
                    "原名が日時プレフィックスを含む。配置済みのツリーをclassifyで処理しようとしている疑いがある",
                )
            )
        else:
            candidates.append(path)

    groups = _members_by_key(request.source, candidates)
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

    return planned


def _preserve_shape_violation(relative: Path, is_symlink: bool) -> str | None:
    """相対配置がYYYY/YYYY-MM/{camera,smartphone}/名前の形から外れていないか確認する。"""

    if is_symlink:
        return "シンボリックリンクである"

    parts = relative.parts
    if len(parts) != 4:
        return "コピー元からの相対配置がYYYY/YYYY-MM/{camera,smartphone}/名前のちょうど4階層でない"

    year_folder, year_month_folder, device_folder, _name = parts
    if YEAR_FOLDER_PATTERN.fullmatch(year_folder) is None:
        return "年フォルダの形式が不正である"

    match = YEAR_MONTH_FOLDER_PATTERN.fullmatch(year_month_folder)
    if match is None:
        return "年月フォルダの形式が不正である"
    if match.group(1) != year_folder:
        return "年フォルダと年月フォルダの年が一致しない"
    if not 1 <= int(match.group(2)) <= 12:
        return "月が01〜12でない"

    if device_folder not in PRESERVE_DEVICE_NAMES:
        return "機器名がcameraまたはsmartphoneではない"

    return None


def _build_preserve_plan(request: CopyRequest, files: Iterable[Path]) -> list[PlannedItem]:
    """コピー元からの相対配置をそのまま配置先へ写す計画を作る。撮影日時は読まない。"""

    planned: list[PlannedItem] = []
    for path in files:
        relative = path.relative_to(request.source)
        key = str(relative)
        violation = _preserve_shape_violation(relative, path.is_symlink())
        if violation is not None:
            planned.append(PlannedItem(path, None, None, key, ItemStatus.UNRESOLVED, violation))
            continue
        planned.append(PlannedItem(path, request.destination_root / relative, None, key, ItemStatus.PLANNED))
    return planned


def build_plan(
    request: CopyRequest,
    *,
    timestamp_for: Callable[[Path], str | None] = capture_timestamp,
) -> tuple[PlannedItem, ...]:
    """コピー元を変更せず、実行前に全ファイルの配置先を決める。

    ``layout=classify`` では基準ファイルを持つ組にその日時を全員に適用し、基準日時が
    取得できない組は全員を未処理にする。``layout=preserve`` では撮影日時を読まず、
    コピー元からの相対配置をそのまま配置先へ写す。いずれのモードでも、モードの
    取り違えを入力の形から検出して未処理にし、OSが作る雑多ファイルは除外にする。
    """

    _validate_layout_arguments(request)
    _validate_only(request.only)

    files = enumerate_files(request.source, only=request.only)
    excluded, remaining = _split_os_junk(request.source, files)

    if request.layout is Layout.PRESERVE:
        planned = _build_preserve_plan(request, remaining)
    else:
        planned = _build_classify_plan(request, remaining, timestamp_for=timestamp_for)

    planned = [_reject_unsafe_destination_name(item) for item in planned]

    return tuple(sorted(excluded + planned, key=lambda item: str(item.source)))


def _reject_unsafe_destination_name(item: PlannedItem) -> PlannedItem:
    """配置先名に改行またはNULを含む場合は未処理にし、転送層へ渡さない。"""

    if item.status is not ItemStatus.PLANNED or item.destination is None:
        return item
    if "\n" in str(item.destination) or "\0" in str(item.destination):
        return PlannedItem(
            item.source, None, item.timestamp, item.group_key, ItemStatus.UNRESOLVED, "配置先名に改行またはNULを含む"
        )
    return item
