"""一時ファイルを使うローカルコピー転送層。"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path

from .transfer import SendOutcome, TransferFailed


class LocalTransfer:
    """SDカードまたはMac上のディレクトリ間でのローカルコピー。"""

    def preflight(self) -> None:
        return None

    def existing(self, destinations: Sequence[Path]) -> frozenset[Path]:
        return frozenset(destination for destination in destinations if destination.exists())

    def ensure_directories(self, directories: Sequence[Path]) -> None:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def send(self, source: Path, destination: Path) -> SendOutcome:
        """上書きをせず、同じディレクトリの一時名を経由してコピーする。"""

        if destination.exists():
            return SendOutcome.EXISTING

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.photo-copy-{uuid.uuid4().hex}.part")
        try:
            shutil.copy2(source, temporary)
            # os.replace() は競合して作られた保存先を上書きしてしまうため使わない。
            # 同一ディレクトリ内の hard link は、保存先が既にある場合に失敗する。
            os.link(temporary, destination)
        except FileExistsError:
            return SendOutcome.EXISTING
        except OSError as error:
            raise TransferFailed(f"ローカルコピーに失敗した: {error}") from error
        finally:
            if temporary.exists():
                temporary.unlink()
        return SendOutcome.COPIED
