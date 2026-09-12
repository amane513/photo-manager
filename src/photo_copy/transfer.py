"""転送方式に依存しない共通処理が使う転送層のプロトコル。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class SendOutcome(str, Enum):
    """1回の ``send()`` が例外を出さずに終わった場合の結果。"""

    COPIED = "copied"
    EXISTING = "existing"


class TransferFailed(RuntimeError):
    """個別ファイルの転送に失敗した場合の例外。残りのファイルは継続する。"""


class TransferAborted(RuntimeError):
    """転送を継続できない場合の例外。残りのファイルは未処理として打ち切る。"""


class TransferUnavailable(RuntimeError):
    """``preflight()`` が転送を開始できないと判断した場合の例外。"""


@dataclass(frozen=True)
class DestinationFacts:
    """配置先の状態。存在しない場合、``is_regular_file`` と ``size`` は意味を持たない。"""

    exists: bool
    is_regular_file: bool
    size: int | None


class Transfer(Protocol):
    """共通処理が転送方式を知らずに使う5操作。"""

    def preflight(self) -> None:
        """接続先や書き込み可否を確認する。失敗時は ``TransferUnavailable`` を送出する。"""

    def facts(self, destinations: Sequence[Path]) -> dict[Path, DestinationFacts]:
        """配置先ごとに、存在するかと通常ファイルであればそのサイズを返す。"""

    def digest(self, destinations: Sequence[Path]) -> dict[Path, str | None]:
        """配置先ごとのSHA-256を返す。計算できない場合はNoneを返す。"""

    def ensure_directories(self, directories: Sequence[Path]) -> None:
        """配置先の親ディレクトリを作る。"""

    def send(self, source: Path, destination: Path) -> SendOutcome:
        """1件をコピーする。失敗時は ``TransferFailed`` または ``TransferAborted`` を送出する。"""
