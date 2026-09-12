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
from .profiles import DEFAULT_PROFILE_CONFIG_PATH, Profile, load_profile
from .rsync import RsyncSshTransfer
from .service import execute_copy, result_as_dict
from .transfer import TransferUnavailable

# 動画のQuickTimeUTC変換に使う既定のTZ。実行ホストの設定に依存すると、動画だけ
# 実行環境によって配置先名が変わり、内容一致によるスキップが効かなくなるため固定する
# （decisions.mdの2026-09-12「動画のTZは固定値とする」を参照）。
DEFAULT_TIMEZONE = "Asia/Tokyo"


def _resolve(cli_value, profile_value, builtin_default):
    """優先順位「コマンドライン引数 > プロファイル > CLIの既定値」で1項目を解決する。"""

    if cli_value is not None:
        return cli_value
    if profile_value is not None:
        return profile_value
    return builtin_default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photo-copy")
    subcommands = parser.add_subparsers(dest="command", required=True)

    copy = subcommands.add_parser("copy", help="ファイルをコピーする")
    copy.add_argument(
        "--source",
        type=Path,
        default=None,
        help="省略時はプロファイルのsourceを使う。プロファイルにも無ければ実行不能",
    )
    copy.add_argument(
        "--destination-root",
        type=Path,
        default=None,
        help=(
            "省略時はプロファイルのdestination-root。"
            "--transport rsync-sshではさらに--host-configのARCHIVE_LIBRARY_ROOTへ落ちる。localでは必須"
        ),
    )
    copy.add_argument(
        "--layout",
        choices=[member.value for member in Layout],
        default=None,
        help="classify: 撮影日時で分類・改名する。preserve: 既存の相対配置を維持する（省略時はプロファイルまたはclassify）",
    )
    copy.add_argument(
        "--year-month",
        metavar="YYYY-MM",
        help=(
            "layout=classifyで指定する。省略時は撮影年月へ自動分類する。"
            "指定時は撮影年月と一致しないファイルを未処理にし、日時不明のファイルは原名のまま指定年月へ配置する。"
            "実行ごとに判断する値であり、プロファイルには書けない"
        ),
    )
    copy.add_argument(
        "--device",
        choices=[member.value for member in Device],
        help="layout=classifyで必須（省略時はプロファイルの値を使う）",
    )
    copy.add_argument(
        "--only",
        action="append",
        metavar="RELATIVE_PATH",
        help="--sourceからの相対パスの部分木に絞り込む。繰り返し指定できる（省略時はプロファイルのonlyを使う）",
    )
    copy.add_argument(
        "--transport",
        choices=[member.value for member in TransferKind],
        default=None,
        help="省略時はプロファイルまたはlocal",
    )
    copy.add_argument(
        "--host-config",
        type=Path,
        default=None,
        help="--transport rsync-sshで必須。scripts/hosts/*.envを指定する（省略時はプロファイルの値を使う）",
    )
    copy.add_argument(
        "--timezone",
        default=None,
        metavar="TZ",
        help=f"ExifToolのQuickTimeUTC変換に使うTZ（省略時はプロファイルまたは固定値{DEFAULT_TIMEZONE}）",
    )
    copy.add_argument(
        "--dry-run",
        action="store_true",
        help="実行ごとに判断する値であり、プロファイルには書けない",
    )
    copy.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="構造化した詳細ログの保存先（省略時はプロファイルまたは./.photo-copy-logs）",
    )
    copy.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help="--profile-configの[profile.NAME]を読み、明示していない項目の既定値にする。省略時はプロファイルを読まない",
    )
    copy.add_argument(
        "--profile-config",
        type=Path,
        default=None,
        metavar="FILE",
        help=f"プロファイル設定ファイル（既定: {DEFAULT_PROFILE_CONFIG_PATH}）。--profileと組み合わせて使う",
    )

    check = subcommands.add_parser("check", help="転送を伴わずに接続先を確認する")
    check.add_argument("--host-config", type=Path, required=True)
    check.add_argument(
        "--destination-root",
        type=Path,
        default=None,
        help="省略時は--host-configのARCHIVE_LIBRARY_ROOT",
    )

    return parser


def _request_from_parsed(
    parsed: argparse.Namespace,
    *,
    profile: Profile | None = None,
    destination_root: Path | None = None,
) -> CopyRequest:
    if parsed.command != "copy":  # pragma: no cover - argparseが保証する。
        raise ValueError(f"未対応のコマンドである: {parsed.command}")

    source = parsed.source or (Path(profile.source) if profile and profile.source else None)
    if source is None:
        raise ValueError("--sourceを指定するか、プロファイルにsourceを設定すること")

    resolved_destination_root = destination_root
    if resolved_destination_root is None:
        resolved_destination_root = parsed.destination_root or (
            Path(profile.destination_root) if profile and profile.destination_root else None
        )
    if resolved_destination_root is None:
        raise ValueError("--destination-rootを指定すること")

    layout_value = _resolve(parsed.layout, profile.layout if profile else None, Layout.CLASSIFY.value)
    transport_value = _resolve(parsed.transport, profile.transport if profile else None, TransferKind.LOCAL.value)
    device_value = _resolve(parsed.device, profile.device if profile else None, None)
    only_value = tuple(parsed.only) if parsed.only else (profile.only if profile else ())

    return CopyRequest(
        source=source,
        destination_root=resolved_destination_root,
        transfer_kind=TransferKind(transport_value),
        layout=Layout(layout_value),
        year_month=parsed.year_month,
        device=Device(device_value) if device_value is not None else None,
        only=only_value,
        dry_run=parsed.dry_run,
    )


def parse_request(arguments: list[str]) -> CopyRequest:
    return _request_from_parsed(build_parser().parse_args(arguments))


def _run_check(parsed: argparse.Namespace) -> int:
    try:
        host_config = load_host_config(parsed.host_config)
        destination_root = parsed.destination_root or host_config.archive_library_root
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


def _load_profile_if_requested(parsed: argparse.Namespace) -> Profile | None:
    """``--profile`` を指定したときだけプロファイルを読む。既定プロファイルの暗黙適用はしない。"""

    if parsed.profile is None:
        return None
    config_path = parsed.profile_config or DEFAULT_PROFILE_CONFIG_PATH
    return load_profile(config_path, parsed.profile)


def _run_copy(parsed: argparse.Namespace) -> int:
    try:
        profile = _load_profile_if_requested(parsed)
    except ValueError as error:
        print(f"実行不能: {error}")
        return 2

    transport_value = _resolve(parsed.transport, profile.transport if profile else None, TransferKind.LOCAL.value)
    host_config_path = parsed.host_config or (Path(profile.host_config) if profile and profile.host_config else None)
    log_dir = _resolve(parsed.log_dir, Path(profile.log_dir) if profile and profile.log_dir else None, Path(".photo-copy-logs"))
    timezone = _resolve(parsed.timezone, profile.timezone if profile else None, DEFAULT_TIMEZONE)

    try:
        transfer_kind = TransferKind(transport_value)

        host_config = None
        if transfer_kind is TransferKind.RSYNC_SSH:
            if host_config_path is None:
                raise ValueError("--transport rsync-sshには--host-configが必要である")
            host_config = load_host_config(host_config_path)

        destination_root = parsed.destination_root or (
            Path(profile.destination_root) if profile and profile.destination_root else None
        )
        if destination_root is None and host_config is not None:
            destination_root = host_config.archive_library_root

        request = _request_from_parsed(parsed, profile=profile, destination_root=destination_root)
        transfer = RsyncSshTransfer(host_config, request.destination_root) if host_config is not None else LocalTransfer()
    except ValueError as error:
        print(f"実行不能: {error}")
        return 2

    if profile is not None:
        print(f"プロファイル: {profile.name} を適用した")
    print(
        "設定: "
        f"コピー元 {request.source}、配置先ルート {request.destination_root}、"
        f"配置モード {request.layout.value}、機種 {request.device.value if request.device is not None else '(preserveのため対象外)'}"
    )

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
    payload["profile"] = profile.name if profile is not None else None
    payload["host_config"] = str(host_config_path) if host_config_path is not None else None
    payload["log_dir"] = str(log_dir)
    payload["timezone"] = resolve_timezone(timezone)
    if isinstance(transfer, RsyncSshTransfer):
        payload["rsync_versions"] = {"local": transfer.local_rsync_version, "remote": transfer.remote_rsync_version}

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"copy-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = result.counts()
    print(
        "結果: "
        f"コピー済み {counts['copied']}件、予定 {counts['planned']}件、"
        f"スキップ {counts['skipped']}件、衝突 {counts['conflict']}件、失敗 {counts['failed']}件、"
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
