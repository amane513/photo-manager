#!/usr/bin/env bash
# Tailscaleを導入・接続し、Immichをtailnet内のHTTPS URLで公開する。
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/../lib/common.sh"
DRY_RUN=false
INSTALL_MISSING=false
CONFIG_PATH=
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --install-missing) INSTALL_MISSING=true; shift ;;
    -h|--help) printf '使い方: sudo setup-tailscale-immich.sh --host-config FILE [--dry-run] [--install-missing]\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
require_root
[[ -n "${IMMICH_PORT:-}" && "$IMMICH_PORT" =~ ^[0-9]+$ ]] || die 'IMMICH_PORTがない、または不正である'

if ! command -v tailscale >/dev/null 2>&1; then
  [[ "$INSTALL_MISSING" == true ]] || die 'Tailscaleがない。確認後に--install-missingを指定すること'
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ Tailscale公式インストーラーを一時ファイルへ取得して実行\n'
  else
    require_command curl
    installer_dir=$(mktemp -d)
    trap 'rm -rf -- "$installer_dir"' EXIT
    curl --fail --silent --show-error --location https://tailscale.com/install.sh \
      --output "$installer_dir/install.sh"
    chmod 0700 "$installer_dir/install.sh"
    "$installer_dir/install.sh"
  fi
fi

run systemctl enable --now tailscaled
if [[ "$DRY_RUN" == true ]]; then
  printf '+ 未認証の場合だけ tailscale up を実行して対話認証\n'
  printf '+ loopback上のImmichを確認後 tailscale serve --bg %q\n' "$IMMICH_PORT"
  printf 'dry-run完了: インストール、tailnet接続、Serve設定は変更していない。\n'
  exit 0
fi

command -v tailscale >/dev/null 2>&1 || die 'Tailscaleの導入を確認できない'
if ! tailscale status --json | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"'; then
  printf 'Ubuntuをtailnetへ追加する。表示されるURLでiPhoneと同じアカウントにログインすること。\n'
  tailscale up
fi
printf 'loopback上のImmichが応答するまで最大60秒待機する。\n'
curl --fail --silent --show-error --max-time 5 \
  --retry 30 --retry-all-errors --retry-delay 2 --retry-max-time 60 \
  --output /dev/null "http://127.0.0.1:$IMMICH_PORT/" \
  || die 'loopback上のImmichへ接続できない。setup-immich.sh --update-config --cudaを先に実行すること'
tailscale serve --bg "$IMMICH_PORT"
printf 'Tailscale Serveを設定した。iPhoneで使うHTTPS URLは次の状態表示で確認すること。\n'
tailscale serve status
