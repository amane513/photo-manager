"""scripts/hosts/*.env の読み込みと検証。

シェルを介さず、``KEY=VALUE`` 形式だけを受け付ける厳密な解析を行う。設定ファイルを
実行しない。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REQUIRED_KEYS = (
    "PRIMARY_STORAGE_UUID",
    "PRIMARY_STORAGE_FSTYPE",
    "ARCHIVE_MOUNT",
    "ARCHIVE_OWNER",
    "ARCHIVE_GROUP",
    "SMB_SHARE_NAME",
    "SMB_VALID_USER",
    "SSH_HOST",
)


@dataclass(frozen=True)
class HostConfig:
    """rsync over SSHの転送先を決める、ホスト固有の設定値。"""

    primary_storage_uuid: str
    primary_storage_fstype: str
    archive_mount: Path
    archive_owner: str
    archive_group: str
    smb_share_name: str
    smb_valid_user: str
    ssh_host: str


def _is_valid_key(key: str) -> bool:
    return bool(key) and (key[0].isalpha() or key[0] == "_") and all(char.isalnum() or char == "_" for char in key)


def _parse_lines(text: str, path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{lineno}: KEY=VALUE形式でない行がある: {raw_line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not _is_valid_key(key):
            raise ValueError(f"{path}:{lineno}: 不正なキーである: {raw_line!r}")
        values[key] = value.strip()
    return values


def load_host_config(path: Path) -> HostConfig:
    """ホスト設定ファイルを読み、必須項目がすべて設定されていることを検証する。"""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"ホスト設定を読めない: {path}: {error}") from error

    values = _parse_lines(text, path)
    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        raise ValueError(f"ホスト設定に必須項目がない: {', '.join(missing)}")

    return HostConfig(
        primary_storage_uuid=values["PRIMARY_STORAGE_UUID"],
        primary_storage_fstype=values["PRIMARY_STORAGE_FSTYPE"],
        archive_mount=Path(values["ARCHIVE_MOUNT"]),
        archive_owner=values["ARCHIVE_OWNER"],
        archive_group=values["ARCHIVE_GROUP"],
        smb_share_name=values["SMB_SHARE_NAME"],
        smb_valid_user=values["SMB_VALID_USER"],
        ssh_host=values["SSH_HOST"],
    )
