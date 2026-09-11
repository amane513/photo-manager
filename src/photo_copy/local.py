"""一時ファイルを使うローカルコピー転送層。"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


class LocalTransferError(RuntimeError):
    """ローカル転送を安全に完了できない場合の例外。"""


def copy_file(source: Path, destination: Path, *, dry_run: bool) -> None:
    """上書きをせず、同じディレクトリの一時名を経由してコピーする。"""

    if destination.exists():
        raise FileExistsError(destination)
    if dry_run:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.photo-copy-{uuid.uuid4().hex}.part")
    try:
        shutil.copy2(source, temporary)
        # os.replace() は競合して作られた保存先を上書きしてしまうため使わない。
        # 同一ディレクトリ内の hard link は、保存先が既にある場合に失敗する。
        os.link(temporary, destination)
    except FileExistsError:
        raise
    except OSError as error:
        raise LocalTransferError(f"ローカルコピーに失敗した: {error}") from error
    finally:
        if temporary.exists():
            temporary.unlink()
