"""photo-copy コマンドの薄い引数処理層。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .models import CopyRequest, Device, Layout, TransferKind
from .service import execute_copy, result_as_dict
from .transfer import TransferUnavailable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photo-copy")
    subcommands = parser.add_subparsers(dest="command", required=True)
    copy = subcommands.add_parser("copy", help="ファイルをコピーする")
    copy.add_argument("--source", type=Path, required=True)
    copy.add_argument("--destination-root", type=Path, required=True)
    copy.add_argument(
        "--layout",
        choices=[member.value for member in Layout],
        default=Layout.CLASSIFY.value,
        help="classify: 撮影日時で分類・改名する（既定）。preserve: 既存の相対配置を維持する。",
    )
    copy.add_argument("--year-month", metavar="YYYY-MM", help="layout=classifyで必須")
    copy.add_argument("--device", choices=[member.value for member in Device], help="layout=classifyで必須")
    copy.add_argument(
        "--only",
        action="append",
        metavar="RELATIVE_PATH",
        help="--sourceからの相対パスの部分木に絞り込む。繰り返し指定できる",
    )
    copy.add_argument(
        "--transport",
        choices=[member.value for member in TransferKind],
        default=TransferKind.LOCAL.value,
    )
    copy.add_argument("--dry-run", action="store_true")
    copy.add_argument(
        "--log-dir",
        type=Path,
        default=Path(".photo-copy-logs"),
        help="構造化した詳細ログの保存先（既定: ./.photo-copy-logs）",
    )
    return parser


def _request_from_parsed(parsed: argparse.Namespace) -> CopyRequest:
    if parsed.command != "copy":  # pragma: no cover - argparseが保証する。
        raise ValueError(f"未対応のコマンドである: {parsed.command}")
    return CopyRequest(
        source=parsed.source,
        destination_root=parsed.destination_root,
        transfer_kind=TransferKind(parsed.transport),
        layout=Layout(parsed.layout),
        year_month=parsed.year_month,
        device=Device(parsed.device) if parsed.device is not None else None,
        only=tuple(parsed.only) if parsed.only else (),
        dry_run=parsed.dry_run,
    )


def parse_request(arguments: list[str]) -> CopyRequest:
    return _request_from_parsed(build_parser().parse_args(arguments))


def main(arguments: list[str] | None = None) -> int:
    parsed = build_parser().parse_args(arguments)
    request = _request_from_parsed(parsed)
    try:
        result = execute_copy(request)
    except (ValueError, NotImplementedError, TransferUnavailable) as error:
        print(f"実行不能: {error}")
        return 2

    payload = result_as_dict(result)
    parsed.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = parsed.log_dir / f"copy-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = result.counts()
    print(
        "結果: "
        f"コピー済み {counts['copied']}件、予定 {counts['planned']}件、"
        f"衝突 {counts['conflict']}件、失敗 {counts['failed']}件、"
        f"未処理 {counts['unresolved']}件、除外 {counts['excluded']}件"
    )
    if result.aborted:
        print(f"中断: {result.abort_reason}")
    print(f"詳細ログ: {log_path}")
    return 0 if not (counts["conflict"] or counts["failed"] or counts["unresolved"]) else 1
