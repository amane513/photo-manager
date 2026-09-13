"""rsync over SSHの転送層。

共通処理が決めた1組の「コピー元・配置先」ごとにrsyncを1回呼ぶ。SSH接続は
OpenSSHのControlMasterで多重化し、接続は ``preflight()`` で確立して ``close()``
（``ssh -O exit``）で破棄する。

リモートへ渡す値はシェル文字列へ直接埋め込まない。検査・作成スクリプトは
標準入力から与え、動的な値は位置引数として渡す。``_run_ssh`` がそれぞれの
引数へ ``shlex.quote`` を通してから1つの文字列へ結合し、SSHへは常に単一の
コマンド引数として渡す。``facts()`` と ``digest()`` だけは対象件数が多くなり
得るため、位置引数ではなくNUL区切りの標準入力でやり取りする。
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .hosts import HostConfig
from .transfer import DestinationFacts, SendOutcome, TransferAborted, TransferFailed, TransferUnavailable

MIN_LOCAL_RSYNC_VERSION = (3, 2, 4)
MIN_REMOTE_RSYNC_VERSION = (3, 2, 6)
SSH_TIMEOUT_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=10")
RSYNC_TIMEOUT_SECONDS = 300
RSYNC_PER_FILE_FAILURE_CODES = frozenset({23, 24})

_VERSION_LINE_PATTERN = re.compile(r"version\s+([0-9]+(?:\.[0-9]+)*)")

_PREFLIGHT_FACTS_SCRIPT = (
    "set -u\n"
    'archive_mount="$1"\n'
    'library_root="$2"\n'
    'destination_root="$3"\n'
    'printf "OWNER=%s\\n" "$(id -un)"\n'
    'if mountpoint -q -- "$archive_mount"; then printf "MOUNTED=1\\n"; else printf "MOUNTED=0\\n"; fi\n'
    # findmntは--targetの引数の前に--（オプション終端）を置くと解釈に失敗するため付けない。
    'printf "UUID=%s\\n" "$(findmnt -n -o UUID --target "$archive_mount" 2>/dev/null)"\n'
    'case "$destination_root" in\n'
    '  "$library_root"|"$library_root"/*) printf "DESTINATION_UNDER_LIBRARY_ROOT=1\\n" ;;\n'
    '  *) printf "DESTINATION_UNDER_LIBRARY_ROOT=0\\n" ;;\n'
    "esac\n"
    'if [ -d "$destination_root" ] && [ -w "$destination_root" ]; then\n'
    '  printf "DESTINATION_WRITABLE=1\\n"\n'
    "else\n"
    '  printf "DESTINATION_WRITABLE=0\\n"\n'
    "fi\n"
    'printf "RSYNC_VERSION_LINE=%s\\n" "$(rsync --version 2>/dev/null | head -n1)"\n'
)

_ENSURE_DIRECTORIES_SCRIPT = 'set -eu\nfor dir; do\n  mkdir -p -- "$dir"\ndone\n'

# 配置先ごとに「値\0パス\0」の並びで返す。存在しない場合はmissing、通常ファイル
# 以外（ディレクトリやシンボリックリンクなど）が存在する場合はother、通常ファイル
# が存在する場合はfile:<バイト数>とする。
_FACTS_SCRIPT = (
    "set -u\n"
    "while IFS= read -r -d '' path; do\n"
    '  if [ -f "$path" ] && [ ! -L "$path" ]; then\n'
    '    size=$(wc -c < "$path" 2>/dev/null | tr -d "[:space:]")\n'
    '    mtime_seconds=$(stat -c %Y -- "$path" 2>/dev/null)\n'
    '    mtime_nanos=$(stat -c %y -- "$path" 2>/dev/null | sed -n "s/.*\\.\\([0-9]\\{9\\}\\).*/\\1/p")\n'
    '    mtime_nanos=${mtime_nanos:-000000000}\n'
    "    printf 'file:%s:%s%s\\0%s\\0' \"$size\" \"$mtime_seconds\" \"$mtime_nanos\" \"$path\"\n"
    '  elif [ -e "$path" ] || [ -L "$path" ]; then\n'
    "    printf 'other\\0%s\\0' \"$path\"\n"
    "  else\n"
    "    printf 'missing\\0%s\\0' \"$path\"\n"
    "  fi\n"
    "done\n"
)

# 配置先ごとに「SHA-256\0パス\0」の並びで返す。計算できない場合は値を空にする。
_DIGEST_SCRIPT = (
    "set -u\n"
    "while IFS= read -r -d '' path; do\n"
    '  sum=$(sha256sum -- "$path" 2>/dev/null | cut -d " " -f1)\n'
    "  printf '%s\\0%s\\0' \"$sum\" \"$path\"\n"
    "done\n"
)


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _parse_version(version_line: str) -> tuple[int, ...] | None:
    match = _VERSION_LINE_PATTERN.search(version_line)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _version_at_least(version: tuple[int, ...] | None, minimum: tuple[int, ...]) -> bool:
    return version is not None and version >= minimum


def _parse_value_path_pairs(data: bytes) -> dict[str, str]:
    """「値\\0パス\\0」の繰り返しを ``{パス: 値}`` の辞書へ変換する。"""

    parts = data.split(b"\0")
    # 末尾はセパレータの後の空要素であるため取り除く。
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    pairs: dict[str, str] = {}
    for index in range(0, len(parts) - 1, 2):
        value = parts[index].decode("utf-8", errors="replace")
        path = parts[index + 1].decode("utf-8", errors="replace")
        pairs[path] = value
    return pairs


def _parse_kv_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


class RsyncSshTransfer:
    """rsync over SSHによる主HDDへの転送。"""

    def __init__(
        self,
        host_config: HostConfig,
        destination_root: Path,
        *,
        run=subprocess.run,
        rsync_executable: str = "rsync",
        uid: int | None = None,
    ) -> None:
        self._host_config = host_config
        self._destination_root = destination_root
        self._run = run
        self._rsync_executable = rsync_executable
        self._control_dir = Path(f"/tmp/photo-copy-{uid if uid is not None else os.getuid()}")
        self._control_path = f"{self._control_dir}/cm-%C"
        self.local_rsync_version: str | None = None
        self.remote_rsync_version: str | None = None

    # --- 内部ヘルパー ---

    def _user_host(self) -> str:
        return f"{self._host_config.archive_owner}@{self._host_config.ssh_host}"

    def _ssh_base_options(self) -> tuple[str, ...]:
        return (*SSH_TIMEOUT_OPTIONS, "-o", f"ControlPath={self._control_path}")

    def _run_ssh(self, remote_args: Sequence[str], *, input_bytes: bytes) -> subprocess.CompletedProcess:
        """リモートコマンドを1つの文字列へ組み立て、SSHへ単一の引数として渡す。"""

        remote_command = " ".join(shlex.quote(str(part)) for part in remote_args)
        command = ["ssh", *self._ssh_base_options(), self._user_host(), remote_command]
        return self._run(command, input=input_bytes, capture_output=True, check=False)

    def _local_rsync_version_line(self) -> str:
        try:
            completed = self._run([self._rsync_executable, "--version"], capture_output=True, check=False)
        except FileNotFoundError as error:
            raise TransferUnavailable("Mac側にrsyncが見つからない") from error
        if completed.returncode != 0:
            raise TransferUnavailable(f"Mac側のrsync --versionが失敗した: {_decode(completed.stderr).strip()}")
        stdout = _decode(completed.stdout)
        return stdout.splitlines()[0] if stdout else ""

    def _reset_control_master(self) -> None:
        self._control_dir.mkdir(parents=True, exist_ok=True)
        self._control_dir.chmod(0o700)
        # 前回のプロセスが残したソケットを破棄してから確立する。存在しない場合の失敗は無視する。
        self._run(
            ["ssh", "-o", f"ControlPath={self._control_path}", "-O", "exit", self._user_host()],
            capture_output=True,
            check=False,
        )
        start = self._run(
            ["ssh", "-M", "-N", "-f", *self._ssh_base_options(), self._user_host()],
            capture_output=True,
            check=False,
        )
        if start.returncode != 0:
            raise TransferUnavailable(f"SSH接続を確立できない: {_decode(start.stderr).strip()}")

    def _remote_facts(self) -> dict[str, str]:
        completed = self._run_ssh(
            [
                "bash",
                "-s",
                "--",
                str(self._host_config.archive_mount),
                str(self._host_config.archive_library_root),
                str(self._destination_root),
            ],
            input_bytes=_PREFLIGHT_FACTS_SCRIPT.encode(),
        )
        if completed.returncode != 0:
            raise TransferUnavailable(f"リモートの検査に失敗した: {_decode(completed.stderr).strip()}")
        return _parse_kv_lines(_decode(completed.stdout))

    # --- Transferプロトコル ---

    def preflight(self) -> None:
        """接続先、マウント、書き込み可否、rsyncの互換性を確認する。"""

        if not self._destination_root.is_absolute():
            raise TransferUnavailable(f"配置先ルートは絶対パスで指定する: {self._destination_root}")
        if not self._destination_root.is_relative_to(self._host_config.archive_library_root):
            raise TransferUnavailable(
                f"配置先ルートが{self._host_config.archive_library_root}配下にない: {self._destination_root}"
            )

        local_version_line = self._local_rsync_version_line()
        local_version = _parse_version(local_version_line)
        if not _version_at_least(local_version, MIN_LOCAL_RSYNC_VERSION):
            raise TransferUnavailable(f"Mac側のrsyncが3.2.4以上でない: {local_version_line.strip()}")
        self.local_rsync_version = local_version_line.strip()

        self._reset_control_master()
        facts = self._remote_facts()

        if facts.get("OWNER") != self._host_config.archive_owner:
            raise TransferUnavailable(f"接続ユーザーが想定と異なる: {facts.get('OWNER')}")
        if facts.get("MOUNTED") != "1":
            raise TransferUnavailable(f"主HDDが未マウントである: {self._host_config.archive_mount}")
        if facts.get("UUID") != self._host_config.primary_storage_uuid:
            raise TransferUnavailable(f"想定外のマウント元UUID: {facts.get('UUID') or '不明'}")
        if facts.get("DESTINATION_UNDER_LIBRARY_ROOT") != "1":
            raise TransferUnavailable(
                f"配置先ルートがライブラリルート{self._host_config.archive_library_root}配下にない: {self._destination_root}"
            )
        if facts.get("DESTINATION_WRITABLE") != "1":
            raise TransferUnavailable(f"配置先ルートへ書き込めない: {self._destination_root}")

        remote_version_line = facts.get("RSYNC_VERSION_LINE", "")
        remote_version = _parse_version(remote_version_line)
        if not _version_at_least(remote_version, MIN_REMOTE_RSYNC_VERSION):
            raise TransferUnavailable(f"リモートのrsyncが3.2.6以上でない: {remote_version_line.strip()}")
        self.remote_rsync_version = remote_version_line.strip()

    def facts(self, destinations: Sequence[Path]) -> dict[Path, DestinationFacts]:
        """配置先の一覧をNUL区切りの標準入力で送り、存在するかとサイズを1回のSSHで受け取る。"""

        if not destinations:
            return {}
        payload = b"".join(str(destination).encode() + b"\0" for destination in destinations)
        completed = self._run_ssh(["bash", "-c", _FACTS_SCRIPT], input_bytes=payload)
        if completed.returncode != 0:
            raise TransferUnavailable(f"配置先の確認に失敗した: {_decode(completed.stderr).strip()}")
        by_path = _parse_value_path_pairs(
            completed.stdout if isinstance(completed.stdout, bytes) else completed.stdout.encode()
        )
        results: dict[Path, DestinationFacts] = {}
        for destination in destinations:
            value = by_path.get(str(destination))
            if value is None:
                continue
            if value == "missing":
                results[destination] = DestinationFacts(exists=False, is_regular_file=False, size=None)
            elif value.startswith("file:"):
                parts = value[len("file:") :].split(":", 1)
                size_text = parts[0]
                size = int(size_text) if size_text.isdigit() else None
                mtime_ns = int(parts[1]) * 1_000_000_000 if len(parts) == 2 and parts[1].isdigit() else None
                results[destination] = DestinationFacts(exists=True, is_regular_file=size is not None, size=size, mtime_ns=mtime_ns)
            else:
                results[destination] = DestinationFacts(exists=True, is_regular_file=False, size=None)
        return results

    def digest(self, destinations: Sequence[Path]) -> dict[Path, str | None]:
        """配置先の一覧をNUL区切りの標準入力で送り、SHA-256を1回のSSHで受け取る。"""

        if not destinations:
            return {}
        payload = b"".join(str(destination).encode() + b"\0" for destination in destinations)
        completed = self._run_ssh(["bash", "-c", _DIGEST_SCRIPT], input_bytes=payload)
        if completed.returncode != 0:
            raise TransferUnavailable(f"配置先のハッシュ計算に失敗した: {_decode(completed.stderr).strip()}")
        by_path = _parse_value_path_pairs(
            completed.stdout if isinstance(completed.stdout, bytes) else completed.stdout.encode()
        )
        return {destination: (by_path.get(str(destination)) or None) for destination in destinations}

    def ensure_directories(self, directories: Sequence[Path]) -> None:
        """必要な配置先の親ディレクトリを、1回のSSHで ``mkdir -p`` する。"""

        if not directories:
            return
        remote_args = ["bash", "-s", "--", *[str(directory) for directory in directories]]
        completed = self._run_ssh(remote_args, input_bytes=_ENSURE_DIRECTORIES_SCRIPT.encode())
        if completed.returncode != 0:
            raise TransferUnavailable(f"ディレクトリ作成に失敗した: {_decode(completed.stderr).strip()}")

    def send(self, source: Path, destination: Path) -> SendOutcome:
        """1件をrsyncで送る。終了コード0かつitemize出力がある場合だけコピー済みとする。"""

        ssh_command = "ssh " + " ".join(shlex.quote(option) for option in self._ssh_base_options())
        remote_target = f"{self._user_host()}:{destination.as_posix()}"
        command = [
            self._rsync_executable,
            "--times",
            "--itemize-changes",
            "--ignore-existing",
            f"--timeout={RSYNC_TIMEOUT_SECONDS}",
            "-e",
            ssh_command,
            "--",
            str(source),
            remote_target,
        ]
        completed = self._run(command, capture_output=True, check=False)
        stdout = _decode(completed.stdout)
        stderr = _decode(completed.stderr)

        if completed.returncode == 0:
            return SendOutcome.COPIED if stdout.strip() else SendOutcome.EXISTING
        if completed.returncode in RSYNC_PER_FILE_FAILURE_CODES:
            raise TransferFailed(f"rsyncが終了コード{completed.returncode}で失敗した: {stderr.strip() or stdout.strip()}")
        raise TransferAborted(f"rsyncが終了コード{completed.returncode}で中断した: {stderr.strip() or stdout.strip()}")

    # --- Transferプロトコル外の後始末 ---

    def close(self) -> None:
        """確立したSSH接続を破棄する。実行終了時に必ず呼ぶこと。"""

        self._run(
            ["ssh", "-o", f"ControlPath={self._control_path}", "-O", "exit", self._user_host()],
            capture_output=True,
            check=False,
        )
