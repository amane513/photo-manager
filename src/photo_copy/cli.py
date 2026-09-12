"""photo-copy コマンドの薄い引数処理層。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .hosts import load_host_config
from .local import LocalTransfer
from .metadata import MetadataError, capture_timestamps, resolve_timezone
from .models import CopyRequest, Device, Layout, TransferKind
from .rsync import RsyncSshTransfer
from .service import execute_copy, result_as_dict
from .transfer import TransferUnavailable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photo-copy")
    subcommands = parser.add_subparsers(dest="command", required=True)

    copy = subcommands.add_parser("copy", help="ファイルをコピーする")
    copy.add_argument("--source", type=Path, required=True)
    copy.add_argument(
        "--destination-root",
        type=Path,
        default=None,
        help="省略時、--transport rsync-sshでは--host-configのARCHIVE_MOUNT。localでは必須",
    )
    copy.add_argument(
        "--layout",
        choices=[member.value for member in Layout],
        default=Layout.CLASSIFY.value,
        help="classify: 撮影日時で分類・改名する（既定）。preserve: 既存の相対配置を維持する。",
    )
    copy.add_argument(
        "--year-month",
        metavar="YYYY-MM",
        help=(
            "layout=classifyで指定する。省略時は撮影年月へ自動分類する。"
            "指定時は撮影年月と一致しないファイルを未処理にし、日時不明のファイルは原名のまま指定年月へ配置する"
        ),
    )
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
    copy.add_argument(
        "--host-config",
        type=Path,
        default=None,
        help="--transport rsync-sshで必須。scripts/hosts/*.envを指定する",
    )
    copy.add_argument(
        "--timezone",
        default=None,
        metavar="TZ",
        help="ExifToolのQuickTimeUTC変換に使うTZ（省略時は実行ホストのタイムゾーン）",
    )
    copy.add_argument("--dry-run", action="store_true")
    copy.add_argument(
        "--log-dir",
        type=Path,
        default=Path(".photo-copy-logs"),
        help="構造化した詳細ログの保存先（既定: ./.photo-copy-logs）",
    )

    check = subcommands.add_parser("check", help="転送を伴わずに接続先を確認する")
    check.add_argument("--host-config", type=Path, required=True)
    check.add_argument(
        "--destination-root",
        type=Path,
        default=None,
        help="省略時は--host-configのARCHIVE_MOUNT",
    )

    return parser


def _request_from_parsed(parsed: argparse.Namespace, *, destination_root: Path | None = None) -> CopyRequest:
    if parsed.command != "copy":  # pragma: no cover - argparseが保証する。
        raise ValueError(f"未対応のコマンドである: {parsed.command}")
    resolved = destination_root if destination_root is not None else parsed.destination_root
    if resolved is None:
        raise ValueError("--destination-rootを指定すること")
    return CopyRequest(
        source=parsed.source,
        destination_root=resolved,
        transfer_kind=TransferKind(parsed.transport),
        layout=Layout(parsed.layout),
        year_month=parsed.year_month,
        device=Device(parsed.device) if parsed.device is not None else None,
        only=tuple(parsed.only) if parsed.only else (),
        dry_run=parsed.dry_run,
    )


def parse_request(arguments: list[str]) -> CopyRequest:
    return _request_from_parsed(build_parser().parse_args(arguments))


def _run_check(parsed: argparse.Namespace) -> int:
    try:
        host_config = load_host_config(parsed.host_config)
        destination_root = parsed.destination_root or host_config.archive_mount
        transfer = RsyncSshTransfer(host_config, destination_root)
    except ValueError as error:
        print(f"実行不能: {error}")
        return 2

    try:
        transfer.preflight()
    except TransferUnavailable as error:
        print(f"実行不能: {error}")
        return 2
    finally:
        transfer.close()

    print(
        "OK: "
        f"接続先 {host_config.ssh_host}、配置先ルート {destination_root}、"
        f"Mac側rsync {transfer.local_rsync_version}、リモートrsync {transfer.remote_rsync_version}"
    )
    return 0


def _run_copy(parsed: argparse.Namespace) -> int:
    transfer_kind = TransferKind(parsed.transport)
    try:
        host_config = None
        if transfer_kind is TransferKind.RSYNC_SSH:
            if parsed.host_config is None:
                raise ValueError("--transport rsync-sshには--host-configが必要である")
            host_config = load_host_config(parsed.host_config)

        destination_root = parsed.destination_root
        if destination_root is None and host_config is not None:
            destination_root = host_config.archive_mount

        request = _request_from_parsed(parsed, destination_root=destination_root)
        transfer = RsyncSshTransfer(host_config, request.destination_root) if host_config is not None else LocalTransfer()
    except ValueError as error:
        print(f"実行不能: {error}")
        return 2

    timezone = parsed.timezone
    timestamps_for = lambda paths: capture_timestamps(paths, tz=timezone)  # noqa: E731

    try:
        try:
            result = execute_copy(request, transfer=transfer, timestamps_for=timestamps_for)
        except (ValueError, NotImplementedError, TransferUnavailable, MetadataError) as error:
            print(f"実行不能: {error}")
            return 2
    finally:
        close = getattr(transfer, "close", None)
        if close is not None:
            close()

    payload = result_as_dict(result)
    payload["timezone"] = resolve_timezone(timezone)
    if isinstance(transfer, RsyncSshTransfer):
        payload["rsync_versions"] = {"local": transfer.local_rsync_version, "remote": transfer.remote_rsync_version}

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


def main(arguments: list[str] | None = None) -> int:
    parsed = build_parser().parse_args(arguments)
    if parsed.command == "check":
        return _run_check(parsed)
    if parsed.command != "copy":  # pragma: no cover - argparseが保証する。
        raise ValueError(f"未対応のコマンドである: {parsed.command}")
    return _run_copy(parsed)
