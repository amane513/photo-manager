#!/usr/bin/env bash
# Tailscale経由のImmich公開状態を変更せずに検査する。
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/../lib/common.sh"
CONFIG_PATH=
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    -h|--help) printf '使い方: sudo verify-tailscale-immich.sh --host-config FILE\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"
[[ -n "${IMMICH_PORT:-}" && "$IMMICH_PORT" =~ ^[0-9]+$ ]] || die 'IMMICH_PORTがない、または不正である'
require_command tailscale
require_command curl
require_command python3

systemctl is-active --quiet tailscaled || die 'tailscaledが起動していない'
tailscale status --json | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"' \
  || die 'Ubuntuがtailnetへ接続していない'
ss -ltnH "sport = :$IMMICH_PORT" | grep -Fq "127.0.0.1:$IMMICH_PORT" \
  || die 'Immichがloopbackで待ち受けていない'
curl --fail --silent --show-error --max-time 5 \
  --output /dev/null "http://127.0.0.1:$IMMICH_PORT/" \
  || die 'loopback上のImmichへ接続できない'
serve_config=$(tailscale serve status --json)
grep -Fq "http://127.0.0.1:$IMMICH_PORT" <<<"$serve_config" \
  || die 'Tailscale Serveの転送先がImmichではない'
dns_name=$(tailscale status --json | python3 -c \
  'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
[[ -n "$dns_name" ]] || die 'TailscaleのDNS名を取得できない'
curl --fail --silent --show-error --max-time 5 \
  --retry 30 --retry-all-errors --retry-delay 2 --retry-max-time 60 \
  --output /dev/null "https://$dns_name/" \
  || die 'Tailscale ServeのHTTPS URLへ接続できない'
printf 'OK: Tailscale経由のImmich公開を確認した。\n'
printf '接続先: https://%s/\n' "$dns_name"
tailscale serve status
