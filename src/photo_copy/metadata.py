"""ExifToolを使った撮影日時の取得。"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path


class MetadataError(RuntimeError):
    """メタデータを安全に取得できない場合の例外。"""


EXIFTOOL_DATE_TAGS = (
    "DateTimeOriginal",
    "MediaCreateDate",
    "CreateDate",
    "TrackCreateDate",
)


def capture_timestamp(
    path: Path,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str | None:
    """撮影日時を ``YYYYMMDD-HHMMSS`` 形式で返す。

    写真はDateTimeOriginal、動画はMediaCreateDateを優先する。QuickTimeの
    UTC時刻はExifToolにローカル時刻へ変換させる。日時がない場合はNoneを返す。
    """

    command = [
        "exiftool",
        "-j",
        "-api",
        "QuickTimeUTC=1",
        "-d",
        "%Y%m%d-%H%M%S",
        *[f"-{tag}" for tag in EXIFTOOL_DATE_TAGS],
        "--",
        str(path),
    ]
    try:
        completed = run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise MetadataError("ExifToolが見つからない") from error

    if completed.returncode != 0:
        raise MetadataError(f"ExifToolが失敗した: {completed.stderr.strip()}")

    try:
        records = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MetadataError("ExifToolのJSON出力を解釈できない") from error

    if len(records) != 1:
        raise MetadataError("ExifToolのJSON出力が不正である")

    record = records[0]
    for tag in EXIFTOOL_DATE_TAGS:
        value = record.get(tag)
        if isinstance(value, str) and value:
            return value
    return None
