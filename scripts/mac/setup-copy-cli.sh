#!/usr/bin/env bash
# Macへphoto-copyとExifToolを導入する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

DRY_RUN=false
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)

usage() {
  printf '使い方: setup-copy-cli.sh [--project-root DIR] [--dry-run]\n'
}

while (($#)); do
  case "$1" in
    --project-root) PROJECT_ROOT=${2:?}; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done

[[ -f "$PROJECT_ROOT/pyproject.toml" ]] || die "photo-managerのプロジェクトルートではない: $PROJECT_ROOT"
require_command brew
require_command python3
require_command rsync

python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
[[ "$python_version" =~ ^3\.([1-9][0-9]|10)$ ]] || die "Python 3.10以上が必要: $python_version"

if command -v exiftool >/dev/null 2>&1; then
  printf 'ExifToolは導入済み: %s\n' "$(exiftool -ver)"
else
  run brew install exiftool
fi

venv="$PROJECT_ROOT/.venv"
if [[ -x "$venv/bin/python" ]]; then
  printf '既存のvenvを使用する: %s\n' "$venv"
else
  run python3 -m venv "$venv"
fi

run "$venv/bin/python" -m pip install --editable "$PROJECT_ROOT"
printf '完了: photo-copy用venvを準備した。続けてverify-copy-cli.shを実行すること。\n'
