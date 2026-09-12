"""~/.config/photo-copy/profiles.ini の読み込みと検証。"""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROFILE_CONFIG_PATH = Path.home() / ".config" / "photo-copy" / "profiles.ini"

ALLOWED_KEYS = (
    "source",
    "destination-root",
    "transport",
    "host-config",
    "layout",
    "device",
    "only",
    "log-dir",
    "timezone",
)

FORBIDDEN_KEYS = ("year-month", "dry-run")


@dataclass(frozen=True)
class Profile:
    """プロファイル設定ファイルから読んだ、1プロファイル分の値。"""

    name: str
    source: str | None = None
    destination_root: str | None = None
    transport: str | None = None
    host_config: str | None = None
    layout: str | None = None
    device: str | None = None
    only: tuple[str, ...] = ()
    log_dir: str | None = None
    timezone: str | None = None


def load_profile(path: Path, name: str) -> Profile:
    """``path`` の ``[profile.<name>]`` セクションを読み、Profileへ変換する。

    ファイルを読めない場合、指定した名前のプロファイルが無い場合、``year-month`` や
    ``dry-run`` が含まれる場合、未知のキーが含まれる場合は ``ValueError`` を送出する。
    """

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"プロファイル設定を読めない: {path}: {error}") from error

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise ValueError(f"{path}: プロファイル設定の形式が不正である: {error}") from error

    section_name = f"profile.{name}"
    if not parser.has_section(section_name):
        raise ValueError(f"プロファイルが見つからない: {name} ({path})")

    keys = parser.options(section_name)

    forbidden = [key for key in keys if key in FORBIDDEN_KEYS]
    if forbidden:
        raise ValueError(
            f"プロファイルに指定できないキーがある（毎回明示する必要がある）: {', '.join(forbidden)}"
        )

    unknown = [key for key in keys if key not in ALLOWED_KEYS]
    if unknown:
        raise ValueError(f"プロファイルに未知のキーがある: {', '.join(unknown)}")

    def get(key: str) -> str | None:
        if key not in keys:
            return None
        return parser.get(section_name, key).strip()

    only_raw = parser.get(section_name, "only") if "only" in keys else ""
    only = tuple(line.strip() for line in only_raw.splitlines() if line.strip())

    return Profile(
        name=name,
        source=get("source"),
        destination_root=get("destination-root"),
        transport=get("transport"),
        host_config=get("host-config"),
        layout=get("layout"),
        device=get("device"),
        only=only,
        log_dir=get("log-dir"),
        timezone=get("timezone"),
    )
