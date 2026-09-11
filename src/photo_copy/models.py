"""CLIから独立したコピー処理で使う値オブジェクト。"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Device(str, Enum):
    CAMERA = "camera"
    SMARTPHONE = "smartphone"


class TransferKind(str, Enum):
    LOCAL = "local"
    RSYNC_SSH = "rsync-ssh"


@dataclass(frozen=True)
class CopyRequest:
    """明示年月で実行する最小版のコピー要求。"""

    source: Path
    destination_root: Path
    year_month: str
    device: Device
    transfer_kind: TransferKind
    dry_run: bool = False
