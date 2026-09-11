"""photo-copy コマンドの薄い引数処理層。"""

from __future__ import annotations

import argparse
from pathlib import Path

from .models import CopyRequest, Device, TransferKind


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photo-copy")
    subcommands = parser.add_subparsers(dest="command", required=True)
    copy = subcommands.add_parser("copy", help="明示年月でファイルをコピーする")
    copy.add_argument("--source", type=Path, required=True)
    copy.add_argument("--destination-root", type=Path, required=True)
    copy.add_argument("--year-month", required=True, metavar="YYYY-MM")
    copy.add_argument("--device", choices=[member.value for member in Device], required=True)
    copy.add_argument(
        "--transport",
        choices=[member.value for member in TransferKind],
        default=TransferKind.LOCAL.value,
    )
    copy.add_argument("--dry-run", action="store_true")
    return parser


def parse_request(arguments: list[str]) -> CopyRequest:
    parsed = build_parser().parse_args(arguments)
    if parsed.command != "copy":  # pragma: no cover - argparseが保証する。
        raise ValueError(f"未対応のコマンドである: {parsed.command}")
    return CopyRequest(
        source=parsed.source,
        destination_root=parsed.destination_root,
        year_month=parsed.year_month,
        device=Device(parsed.device),
        transfer_kind=TransferKind(parsed.transport),
        dry_run=parsed.dry_run,
    )


def main(arguments: list[str] | None = None) -> int:
    request = parse_request(arguments)
    print(
        "未実装: "
        f"{request.source} から {request.destination_root} へ "
        f"{request.year_month}/{request.device.value} としてコピーする"
    )
    return 0
