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


class ItemStatus(str, Enum):
    """コピー計画または実行における各ファイルの状態。"""

    PLANNED = "planned"
    COPIED = "copied"
    CONFLICT = "conflict"
    FAILED = "failed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class CopyRequest:
    """明示年月で実行する最小版のコピー要求。"""

    source: Path
    destination_root: Path
    year_month: str
    device: Device
    transfer_kind: TransferKind
    dry_run: bool = False


@dataclass(frozen=True)
class PlannedItem:
    """日時と組の規則を適用した一つのコピー予定。"""

    source: Path
    destination: Path | None
    timestamp: str | None
    group_key: str
    status: ItemStatus
    reason: str | None = None


@dataclass(frozen=True)
class CopyResult:
    """一つのコピー要求の構造化結果。"""

    request: CopyRequest
    items: tuple[PlannedItem, ...]

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in ItemStatus}
        for item in self.items:
            counts[item.status.value] += 1
        return counts
