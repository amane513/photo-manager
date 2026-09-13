#!/usr/bin/env bash
# Macのphoto-copy実行環境を変更せずに検査する。

set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=../lib/common.sh
source "$SCRIPT_DIR/../lib/common.sh"

PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)

while (($#)); do
  case "$1" in
    --project-root) PROJECT_ROOT=${2:?}; shift 2 ;;
    -h|--help) printf '使い方: verify-copy-cli.sh [--project-root DIR]\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done

require_command python3
require_command rsync
require_command exiftool
venv="$PROJECT_ROOT/.venv"
[[ -x "$venv/bin/python" ]] || die "venvがない: $venv"
[[ -x "$venv/bin/photo-copy" ]] || die "photo-copyがvenvへ導入されていない"
"$venv/bin/python" -c 'from photo_copy.verification import verify_copy; from photo_copy.models import VerificationResult; assert callable(verify_copy); assert VerificationResult' \
  || die "全件検証APIを読み込めない"

python_version=$($venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
[[ "$python_version" =~ ^3\.([1-9][0-9]|10)$ ]] || die "Python 3.10以上が必要: $python_version"
rsync_version=$(rsync --version | sed -n '1s/^rsync  version \([0-9.]*\).*/\1/p')
[[ "$rsync_version" =~ ^3\. ]] || die "rsync 3系が必要: ${rsync_version:-不明}"

printf 'OK: Python %s、rsync %s（%s）、ExifTool %s、全件検証対応のphoto-copyを確認した。\n' \
  "$python_version" "$rsync_version" "$(command -v rsync)" "$(exiftool -ver)"
