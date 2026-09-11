"""配置計画を転送層へ渡し、構造化結果を返す共通API。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .local import LocalTransferError, copy_file
from .models import CopyRequest, CopyResult, ItemStatus, PlannedItem, TransferKind
from .planning import build_plan


def execute_copy(request: CopyRequest, *, timestamp_for=None) -> CopyResult:
    """ローカルコピーを実行する。rsync転送は実装されるまで明示的に拒否する。"""

    if request.transfer_kind is not TransferKind.LOCAL:
        raise NotImplementedError("rsync over SSH転送は未実装である")
    plan = build_plan(request, **({"timestamp_for": timestamp_for} if timestamp_for else {}))
    destination_counts: dict[Path, int] = {}
    for item in plan:
        if item.status is ItemStatus.PLANNED and item.destination is not None:
            destination_counts[item.destination] = destination_counts.get(item.destination, 0) + 1

    results: list[PlannedItem] = []
    for item in plan:
        if item.status is not ItemStatus.PLANNED:
            results.append(item)
            continue
        assert item.destination is not None
        if destination_counts[item.destination] > 1:
            results.append(replace(item, status=ItemStatus.CONFLICT, reason="同じ保存先名になる入力が複数ある"))
            continue
        if item.destination.exists():
            results.append(replace(item, status=ItemStatus.CONFLICT, reason="同名の保存先ファイルが存在する"))
            continue
        try:
            copy_file(item.source, item.destination, dry_run=request.dry_run)
        except FileExistsError:
            results.append(replace(item, status=ItemStatus.CONFLICT, reason="同名の保存先ファイルが存在する"))
        except LocalTransferError as error:
            results.append(replace(item, status=ItemStatus.FAILED, reason=str(error)))
        else:
            results.append(replace(item, status=ItemStatus.PLANNED if request.dry_run else ItemStatus.COPIED))
    return CopyResult(request, tuple(results))


def result_as_dict(result: CopyResult) -> dict[str, object]:
    """ログや将来のGUIで利用するJSON互換の結果を作る。"""

    return {
        "source": str(result.request.source),
        "destination_root": str(result.request.destination_root),
        "year_month": result.request.year_month,
        "device": result.request.device.value,
        "transport": result.request.transfer_kind.value,
        "dry_run": result.request.dry_run,
        "counts": result.counts(),
        "items": [
            {
                "source": str(item.source),
                "destination": str(item.destination) if item.destination else None,
                "timestamp": item.timestamp,
                "group_key": item.group_key,
                "status": item.status.value,
                "reason": item.reason,
            }
            for item in result.items
        ],
    }
