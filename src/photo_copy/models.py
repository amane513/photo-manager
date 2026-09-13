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
    SKIPPED = "skipped"
    CONFLICT = "conflict"
    FAILED = "failed"
    UNRESOLVED = "unresolved"
    NOT_TARGETED = "not-targeted"
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
    # 既存一致の判定で取得済みの値。検証で同じファイルを再読しないために保持する。
    matched_evidence: dict[Path, tuple[int, str]] | None = None

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in ItemStatus}
        for item in self.items:
            counts[item.status.value] += 1
        return counts


class VerificationStatus(str, Enum):
    """コピー完了後の内容検証における各ファイルの状態。"""

    MATCHED = "matched"
    MISSING = "missing"
    DIFFERENT = "different"
    INVALID_DESTINATION = "invalid-destination"
    UNREADABLE = "unreadable"
    UNRESOLVED = "unresolved"
    NOT_TARGETED = "not-targeted"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class VerificationItem:
    """一つのコピー元と配置先の検証結果。"""

    source: Path
    destination: Path | None
    destination_relative: Path | None
    status: VerificationStatus
    source_size: int | None = None
    source_sha256: str | None = None
    destination_size: int | None = None
    destination_sha256: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    """全保存対象の読み取り専用検証結果。"""

    items: tuple[VerificationItem, ...]
    manifest_sha256: str | None = None
    not_run: bool = False
    abort_reason: str | None = None

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in VerificationStatus}
        for item in self.items:
            counts[item.status.value] += 1
        return counts

    def totals(self) -> tuple[int, int, int, int]:
        targets = [item for item in self.items if item.status not in {VerificationStatus.NOT_TARGETED, VerificationStatus.EXCLUDED}]
        matched = [item for item in self.items if item.status is VerificationStatus.MATCHED]
        return len(targets), sum(item.source_size or 0 for item in targets), len(matched), sum(item.source_size or 0 for item in matched)

    @property
    def successful(self) -> bool:
        return not self.not_run and all(item.status in {VerificationStatus.MATCHED, VerificationStatus.NOT_TARGETED, VerificationStatus.EXCLUDED} for item in self.items)


@dataclass(frozen=True)
class CopyExecutionResult:
    """転送結果と検証結果を一つの利用者操作として束ねる。"""

    copy: CopyResult
    verification: VerificationResult
    copy_duration_seconds: float = 0.0
    verification_duration_seconds: float = 0.0

    # 旧来の共通API利用者との互換性のため、コピー結果を透過して公開する。
    @property
    def request(self) -> CopyRequest:
        return self.copy.request

    @property
    def items(self) -> tuple[PlannedItem, ...]:
        return self.copy.items

    @property
    def aborted(self) -> bool:
        return self.copy.aborted

    @property
    def abort_reason(self) -> str | None:
        return self.copy.abort_reason

    def counts(self) -> dict[str, int]:
        return self.copy.counts()
