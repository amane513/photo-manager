"""配置計画を転送層へ渡し、構造化結果を返す共通API。

転送方式（ローカルコピー、rsync over SSHなど）の詳細は :mod:`transfer` の
プロトコルに従う実装へ委ねる。ここでは計画・衝突判定・結果生成だけを行う。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import monotonic

from .digest import file_digest
from .local import LocalTransfer
from .models import CopyExecutionResult, CopyRequest, CopyResult, ItemStatus, PlannedItem, TransferKind
from .planning import build_plan
from .transfer import SendOutcome, Transfer, TransferAborted, TransferFailed, TransferUnavailable


def _default_transfer(request: CopyRequest) -> Transfer:
    """``--transport`` から転送層を選ぶ既定の対応付け。"""

    if request.transfer_kind is TransferKind.LOCAL:
        return LocalTransfer()
    raise NotImplementedError("rsync over SSH転送は未実装である")


def _resolve_content_match(
    candidates: list[PlannedItem],
    *,
    transfer: Transfer,
    source_digest_for: Callable[[Path], str],
) -> tuple[dict[Path, PlannedItem], dict[Path, tuple[int, str]]]:
    """配置先の事実とハッシュから、スキップ・衝突・失敗を確定する。

    サイズが異なる時点で衝突とし、ハッシュを計算しない。存在しない配置先は
    対象から外し、転送予定のまま呼び出し元へ返す。戻り値はコピー元パスを
    キーにした、判定が確定した項目だけの辞書である。
    """

    if not candidates:
        return {}, {}

    try:
        facts = transfer.facts([item.destination for item in candidates])  # type: ignore[arg-type]
    except (OSError, TransferUnavailable) as error:
        return ({item.source: replace(item, status=ItemStatus.FAILED, reason=f"existing-destination-unreadable: {error}") for item in candidates}, {})

    pending_digest: list[tuple[PlannedItem, object, int]] = []
    resolved: dict[Path, PlannedItem] = {}
    evidence: dict[Path, tuple[int, str]] = {}
    for item in candidates:
        fact = facts.get(item.destination)
        if fact is None:
            resolved[item.source] = replace(item, status=ItemStatus.FAILED, reason="existing-destination-unreadable: 配置先情報が返らない")
            continue
        if not fact.exists:
            continue
        if not fact.is_regular_file:
            resolved[item.source] = replace(item, status=ItemStatus.CONFLICT, reason="existing-invalid-destination: 同名のファイル以外が存在する")
            continue
        try:
            source_stat = item.source.stat()
            source_size = source_stat.st_size
        except OSError as error:
            resolved[item.source] = replace(item, status=ItemStatus.FAILED, reason=f"existing-source-unreadable: {error}")
            continue
        if fact.size != source_size:
            resolved[item.source] = replace(item, status=ItemStatus.CONFLICT, reason="existing-different: 同名で内容が異なる")
            continue
        pending_digest.append((item, source_stat, source_size))

    if pending_digest:
        try:
            destination_digests = transfer.digest([item.destination for item, _, _ in pending_digest])  # type: ignore[arg-type]
        except (OSError, TransferUnavailable) as error:
            resolved.update({item.source: replace(item, status=ItemStatus.FAILED, reason=f"existing-destination-unreadable: {error}") for item, _, _ in pending_digest})
            return resolved, evidence
        for item, source_stat, source_size in pending_digest:
            try:
                source_hash = source_digest_for(item.source)
            except OSError as error:
                resolved[item.source] = replace(
                    item, status=ItemStatus.FAILED, reason=f"existing-source-unreadable: {error}"
                )
                continue
            destination_hash = destination_digests.get(item.destination)
            if destination_hash is None:
                resolved[item.source] = replace(item, status=ItemStatus.FAILED, reason="existing-destination-unreadable: 配置先ハッシュが返らない")
            elif destination_hash == source_hash:
                resolved[item.source] = replace(item, status=ItemStatus.SKIPPED, reason="内容が同一のため転送しない")
                # source_sizeは直前のfacts比較で一致済みである。
                after = item.source.stat()
                if (after.st_size, after.st_mtime_ns) == (source_stat.st_size, source_stat.st_mtime_ns):
                    evidence[item.source] = (source_size, source_hash)
                else:
                    resolved[item.source] = replace(item, status=ItemStatus.FAILED, reason="既存一致の確認中にコピー元が変化した")
            else:
                resolved[item.source] = replace(item, status=ItemStatus.CONFLICT, reason="existing-different: 同名で内容が異なる")

    return resolved, evidence


def execute_copy(
    request: CopyRequest,
    *,
    timestamps_for=None,
    transfer: Transfer | None = None,
    source_digest_for: Callable[[Path], str] = file_digest,
) -> CopyExecutionResult:
    """計画を作り、転送層の5操作だけを使ってコピーを実行する。

    処理順は次に固定する。

    1. ``build_plan`` で全ファイルの配置先を決める。
    2. ``preflight()`` を実行する（失敗時は ``TransferUnavailable`` が伝播する）。
    3. 入力内で同じ配置先名になる項目を衝突にする。
    4. ``facts()`` で配置先の存在とサイズを取得し、サイズが同じものだけ ``digest()``
       とコピー元のハッシュを比較して、スキップと衝突を確定する。
    5. dry-runの場合はここで結果を返す。
    6. ``ensure_directories()`` で必要な親ディレクトリを作る。
    7. 1件ずつ ``send()`` する。個別失敗は継続し、中断は残りを未処理にして打ち切る。
    """

    started = monotonic()
    if transfer is None:
        transfer = _default_transfer(request)

    plan = build_plan(request, **({"timestamps_for": timestamps_for} if timestamps_for else {}))

    transfer.preflight()

    destination_counts: dict[Path, int] = {}
    for item in plan:
        if item.status is ItemStatus.PLANNED and item.destination is not None:
            destination_counts[item.destination] = destination_counts.get(item.destination, 0) + 1

    working: list[PlannedItem] = [
        replace(item, status=ItemStatus.CONFLICT, reason="同じ保存先名になる入力が複数ある")
        if item.status is ItemStatus.PLANNED and item.destination is not None and destination_counts[item.destination] > 1
        else item
        for item in plan
    ]

    candidates = [item for item in working if item.status is ItemStatus.PLANNED and item.destination is not None]
    resolved, evidence = _resolve_content_match(candidates, transfer=transfer, source_digest_for=source_digest_for)
    working = [resolved.get(item.source, item) for item in working]

    if request.dry_run:
        from .verification import verify_copy
        copy = CopyResult(request, tuple(working), matched_evidence=evidence)
        copy_duration = monotonic() - started
        verification_started = monotonic()
        verification = verify_copy(copy, transfer=transfer, source_digest_for=source_digest_for)
        return CopyExecutionResult(copy, verification, copy_duration, monotonic() - verification_started)

    directories = sorted(
        {item.destination.parent for item in working if item.status is ItemStatus.PLANNED and item.destination is not None},
        key=str,
    )
    transfer.ensure_directories(directories)

    results: list[PlannedItem] = []
    aborted = False
    abort_reason: str | None = None
    for item in working:
        if item.status is not ItemStatus.PLANNED:
            results.append(item)
            continue
        if aborted:
            results.append(replace(item, status=ItemStatus.UNRESOLVED, reason="転送中断のため未処理"))
            continue
        assert item.destination is not None
        try:
            outcome = transfer.send(item.source, item.destination)
        except TransferFailed as error:
            results.append(replace(item, status=ItemStatus.FAILED, reason=str(error)))
        except TransferAborted as error:
            aborted = True
            abort_reason = str(error)
            results.append(replace(item, status=ItemStatus.FAILED, reason=str(error)))
        else:
            if outcome is SendOutcome.EXISTING:
                results.append(
                    replace(
                        item,
                        status=ItemStatus.CONFLICT,
                        reason="転送直前に同名の保存先ファイルが現れた（内容一致とはみなさない）",
                    )
                )
            else:
                results.append(replace(item, status=ItemStatus.COPIED))

    from .verification import verify_copy

    copy = CopyResult(request, tuple(results), aborted=aborted, abort_reason=abort_reason, matched_evidence=evidence)
    copy_duration = monotonic() - started
    verification_started = monotonic()
    verification = verify_copy(copy, transfer=transfer, source_digest_for=source_digest_for)
    return CopyExecutionResult(copy, verification, copy_duration, monotonic() - verification_started)


def result_as_dict(result: CopyExecutionResult) -> dict[str, object]:
    """ログや将来のGUIで利用するJSON互換の結果を作る。"""

    return {
        "schema_version": 2,
        "copy_duration_seconds": result.copy_duration_seconds,
        "verification_duration_seconds": result.verification_duration_seconds,
        "source": str(result.request.source),
        "destination_root": str(result.request.destination_root),
        "layout": result.request.layout.value,
        "year_month": result.request.year_month,
        "device": result.request.device.value if result.request.device is not None else None,
        "only": list(result.request.only),
        "transport": result.request.transfer_kind.value,
        "dry_run": result.request.dry_run,
        "aborted": result.aborted,
        "abort_reason": result.abort_reason,
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
        "verification": {
            "not_run": result.verification.not_run,
            "abort_reason": result.verification.abort_reason,
            "counts": result.verification.counts(),
            "manifest_sha256": result.verification.manifest_sha256,
            "totals": {
                "target_count": result.verification.totals()[0], "target_bytes": result.verification.totals()[1],
                "matched_count": result.verification.totals()[2], "matched_bytes": result.verification.totals()[3],
            },
            "items": [
                {
                    "source": str(item.source), "destination": str(item.destination) if item.destination else None,
                    "destination_relative": str(item.destination_relative) if item.destination_relative else None,
                    "status": item.status.value, "source_size": item.source_size,
                    "source_sha256": item.source_sha256, "destination_size": item.destination_size,
                    "destination_sha256": item.destination_sha256, "reason": item.reason,
                }
                for item in result.verification.items
            ],
        },
    }
