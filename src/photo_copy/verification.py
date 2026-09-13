"""コピー後に配置結果だけを読む全件検証API。"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from .digest import file_digest
from .models import CopyResult, ItemStatus, VerificationItem, VerificationResult, VerificationStatus
from .transfer import ReadOnlyTransfer, TransferUnavailable


def _source_digest(path: Path, digest_for: Callable[[Path], str]) -> tuple[int, str]:
    """ハッシュ計算の前後でコピー元が変わっていないことも確認する。"""

    before = path.stat()
    value = digest_for(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError("ハッシュ計算中にコピー元が変化した")
    return before.st_size, value


def _manifest(items: list[VerificationItem]) -> str | None:
    if any(item.status is not VerificationStatus.MATCHED for item in items if item.status not in {VerificationStatus.NOT_TARGETED, VerificationStatus.EXCLUDED}):
        return None
    digest = hashlib.sha256()
    for item in sorted((item for item in items if item.status is VerificationStatus.MATCHED), key=lambda item: str(item.destination_relative)):
        assert item.destination_relative is not None and item.source_size is not None and item.source_sha256 is not None
        digest.update(str(item.destination_relative).encode("utf-8") + b"\0")
        digest.update(str(item.source_size).encode("ascii") + b"\0")
        digest.update(item.source_sha256.encode("ascii") + b"\n")
    return digest.hexdigest()


def verify_copy(
    copy: CopyResult,
    *,
    transfer: ReadOnlyTransfer,
    source_digest_for: Callable[[Path], str] = file_digest,
) -> VerificationResult:
    """コピー結果を検証する。書き込み系の転送APIは一切使用しない。"""

    if copy.request.dry_run:
        return VerificationResult((), not_run=True, abort_reason="dry-runでは検証しない")
    if copy.aborted:
        return VerificationResult((), not_run=True, abort_reason=copy.abort_reason or "転送が中断した")

    prelim: list[VerificationItem] = []
    to_read: list[tuple[object, int, str]] = []
    evidence = copy.matched_evidence or {}
    for item in copy.items:
        relative = item.destination.relative_to(copy.request.destination_root) if item.destination is not None else None
        if item.status is ItemStatus.NOT_TARGETED:
            prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.NOT_TARGETED, reason=item.reason))
        elif item.status is ItemStatus.EXCLUDED:
            prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.EXCLUDED, reason=item.reason))
        elif item.status is ItemStatus.SKIPPED and item.source in evidence:
            size, sha = evidence[item.source]
            prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.MATCHED, size, sha, size, sha))
        elif item.status is ItemStatus.COPIED:
            try:
                size, sha = _source_digest(item.source, source_digest_for)
            except OSError as error:
                prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.UNREADABLE, reason=str(error)))
            else:
                to_read.append((item, size, sha))
        else:
            reason = item.reason or "コピー結果が検証可能でない"
            if reason.startswith("existing-different:"):
                status = VerificationStatus.DIFFERENT
            elif reason.startswith("existing-invalid-destination:"):
                status = VerificationStatus.INVALID_DESTINATION
            elif "unreadable:" in reason:
                status = VerificationStatus.UNREADABLE
            else:
                status = VerificationStatus.UNRESOLVED
            prelim.append(VerificationItem(item.source, item.destination, relative, status, reason=reason))

    destinations = [item.destination for item, _, _ in to_read if item.destination is not None]
    if destinations:
        try:
            facts = transfer.facts(destinations)
            readable = [destination for destination in destinations if facts.get(destination) and facts[destination].exists and facts[destination].is_regular_file]
            hashes = transfer.digest(readable)
        except TransferUnavailable as error:
            return VerificationResult(tuple(prelim), not_run=True, abort_reason=f"コピー後検証を完了できない: {error}")
        except OSError as error:
            return VerificationResult(tuple(prelim + [
                VerificationItem(item.source, item.destination, item.destination.relative_to(copy.request.destination_root), VerificationStatus.UNREADABLE, size, sha, reason=str(error))
                for item, size, sha in to_read
            ]))
        try:
            after_facts = transfer.facts(readable)
        except TransferUnavailable as error:
            return VerificationResult(tuple(prelim), not_run=True, abort_reason=f"コピー後検証を完了できない: {error}")
        except OSError as error:
            return VerificationResult(tuple(prelim + [
                VerificationItem(item.source, item.destination, item.destination.relative_to(copy.request.destination_root), VerificationStatus.UNREADABLE, size, sha, reason=str(error))
                for item, size, sha in to_read
            ]))
    else:
        facts = {}
        hashes = {}
        after_facts = {}

    for item, source_size, source_hash in to_read:
        assert item.destination is not None
        relative = item.destination.relative_to(copy.request.destination_root)
        fact = facts.get(item.destination)
        if fact is None:
            prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.UNREADABLE, source_size, source_hash, reason="配置先情報が返らない"))
        elif not fact.exists:
            prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.MISSING, source_size, source_hash))
        elif not fact.is_regular_file:
            prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.INVALID_DESTINATION, source_size, source_hash))
        elif fact.size != source_size:
            prelim.append(VerificationItem(item.source, item.destination, relative, VerificationStatus.DIFFERENT, source_size, source_hash, fact.size))
        else:
            destination_hash = hashes.get(item.destination)
            after = after_facts.get(item.destination)
            if destination_hash is None:
                status, reason = VerificationStatus.UNREADABLE, "配置先ハッシュが返らない"
            elif after is None:
                status, reason = VerificationStatus.UNREADABLE, "ハッシュ後の配置先情報が返らない"
            elif (after.size, after.mtime_ns) != (fact.size, fact.mtime_ns):
                status, reason = VerificationStatus.DIFFERENT, "検証中に配置先が変化した"
            elif destination_hash != source_hash:
                status, reason = VerificationStatus.DIFFERENT, None
            else:
                status, reason = VerificationStatus.MATCHED, None
            prelim.append(VerificationItem(item.source, item.destination, relative, status, source_size, source_hash, fact.size, destination_hash, reason))

    return VerificationResult(tuple(prelim), manifest_sha256=_manifest(prelim))
