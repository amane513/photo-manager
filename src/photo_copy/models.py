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


class Layout(str, Enum):
    """配置の決め方。分類するか、既存の相対配置を維持するかを利用者が明示する。"""

    CLASSIFY = "classify"
    PRESERVE = "preserve"


class ItemStatus(str, Enum):
    """コピー計画または実行における各ファイルの状態。"""

    PLANNED = "planned"
    COPIED = "copied"
    CONFLICT = "conflict"
    FAILED = "failed"
    UNRESOLVED = "unresolved"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class CopyRequest:
    """最小版のコピー要求。

    ``layout`` が ``classify`` の場合は ``year_month`` と ``device`` が必須であり、
    ``preserve`` の場合はこの2つを指定できない。
    """

    source: Path
    destination_root: Path
    transfer_kind: TransferKind
    layout: Layout = Layout.CLASSIFY
    year_month: str | None = None
    device: Device | None = None
    only: tuple[str, ...] = ()
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
    aborted: bool = False
    abort_reason: str | None = None

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in ItemStatus}
        for item in self.items:
            counts[item.status.value] += 1
        return counts
