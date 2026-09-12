"""ExifToolを使った撮影日時の取得。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path


class MetadataError(RuntimeError):
    """メタデータを安全に取得できない場合の例外。"""


EXIFTOOL_DATE_TAGS = (
    "DateTimeOriginal",
    "MediaCreateDate",
    "CreateDate",
    "TrackCreateDate",
)

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S"
MIN_VALID_TIMESTAMP = datetime(1990, 1, 1, 0, 0, 0)


def resolve_timezone(tz: str | None) -> str:
    """ExifToolへ与えるTZの値を決める。

    明示指定があればそれをそのまま使う。省略時は実行ホストのタイムゾーンとし、
    ログへ記録できるよう ``+HHMM`` 形式のUTCオフセットで表す。
    """

    if tz is not None:
        return tz
    return time.strftime("%z") or "+0000"


def _build_argfile(paths: Sequence[Path]) -> bytes:
    """``-@ -`` で読む引数ファイルの内容を組み立てる。1行に1引数を書く。"""

    lines = [
        "-j",
        "-api",
        "QuickTimeUTC=1",
        "-d",
        TIMESTAMP_FORMAT,
        *[f"-{tag}" for tag in EXIFTOOL_DATE_TAGS],
        "--",
        *[str(path) for path in paths],
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def capture_timestamps(
    paths: Sequence[Path],
    *,
    tz: str | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[Path, str | None]:
    """撮影日時を ``YYYYMMDD-HHMMSS`` 形式で一括取得する。

    ``exiftool -@ -`` に対象パスを標準入力から渡し、引数長の上限に依存しない。
    写真はDateTimeOriginal、動画はMediaCreateDateを優先する。QuickTimeの
    UTC時刻はExifToolにローカル時刻へ変換させる。変換に使うタイムゾーンは
    ``tz`` で明示でき、省略時は実行ホストのタイムゾーンに任せる。

    一括呼び出しそのものが失敗した場合（ExifToolが見つからない、JSON出力を
    解釈できない、返ってきた件数が渡した件数と一致しないなど）は
    ``MetadataError`` を送出する。個々のファイルに日時タグが無い場合はそのファイルの
    値をNoneにするだけで、他のファイルの結果には影響させない。
    """

    if not paths:
        return {}

    env = {**os.environ, "TZ": tz} if tz is not None else None
    try:
        completed = run(
            ["exiftool", "-@", "-"],
            input=_build_argfile(paths),
            capture_output=True,
            check=False,
            env=env,
        )
    except FileNotFoundError as error:
        raise MetadataError("ExifToolが見つからない") from error

    stdout = completed.stdout
    stdout_text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout
    try:
        records = json.loads(stdout_text)
    except json.JSONDecodeError as error:
        raise MetadataError("ExifToolのJSON出力を解釈できない") from error

    if not isinstance(records, list) or len(records) != len(paths):
        raise MetadataError("ExifToolのJSON出力の件数が要求と一致しない")

    results: dict[Path, str | None] = {}
    for path, record in zip(paths, records):
        results[path] = _extract_timestamp(record)
    return results


def _extract_timestamp(record: dict) -> str | None:
    for tag in EXIFTOOL_DATE_TAGS:
        value = record.get(tag)
        if isinstance(value, str) and value:
            return value
    return None


def capture_timestamp(
    path: Path,
    *,
    tz: str | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str | None:
    """1件だけの撮影日時を返す。``capture_timestamps`` の薄い包みである。"""

    return capture_timestamps([path], tz=tz, run=run).get(path)


def is_timestamp_in_valid_range(value: str, *, now: datetime | None = None) -> bool:
    """撮影日時が1990-01-01以降かつ実行時刻の翌日以前かを検査する。

    カメラの電池切れなどによる時計リセットで、実在しない年月のフォルダが
    主HDDへ作られることを防ぐ。
    """

    try:
        parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        return False
    reference_now = now if now is not None else datetime.now()
    return MIN_VALID_TIMESTAMP <= parsed <= reference_now + timedelta(days=1)
