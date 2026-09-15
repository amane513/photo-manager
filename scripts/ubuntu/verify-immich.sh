#!/usr/bin/env bash
# Immichの実行状態と原本保護を変更せずに検査する。
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/../lib/common.sh"
CONFIG_PATH=; REQUIRE_CUDA=false
while (($#)); do case "$1" in --host-config) CONFIG_PATH=${2:?}; shift 2;; --require-cuda) REQUIRE_CUDA=true; shift;; -h|--help) printf '使い方: sudo verify-immich.sh --host-config FILE [--require-cuda]\n'; exit 0;; *) die "不明な引数: $1";; esac; done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'; load_host_config "$CONFIG_PATH"; require_root
for name in IMMICH_ROOT IMMICH_LAN_BIND_ADDRESS IMMICH_PORT IMMICH_VERSION ARCHIVE_LIBRARY_ROOT; do [[ -n "${!name:-}" ]] || die "ホスト設定に $name がない"; done
app="$IMMICH_ROOT/app"; env_file="$app/.env"
[[ $(stat -c '%U:%G:%a' "$env_file") == root:root:600 ]] || die '.envの所有者または権限が安全でない'
grep -Fxq "IMMICH_VERSION=$IMMICH_VERSION" "$env_file" || die '固定バージョンが一致しない'
for dir in "$IMMICH_ROOT/data" "$IMMICH_ROOT/postgres" "$IMMICH_ROOT/model-cache"; do [[ -d "$dir" ]] || die "不足: $dir"; done
for container in immich_postgres immich_redis immich_server immich_machine_learning; do
  state=$(docker inspect "$container" --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null) || die "コンテナがない: $container"
  [[ "$state" == 'running healthy' || "$state" == 'running ' ]] || die "コンテナが正常ではない: $container ($state)"
done
ss -ltnH "sport = :$IMMICH_PORT" | grep -Fq "$IMMICH_LAN_BIND_ADDRESS:$IMMICH_PORT" || die 'LAN bindが一致しない'
ss -ltnH "sport = :$IMMICH_PORT" | grep -Fq "127.0.0.1:$IMMICH_PORT" || die 'Tailscale Serve用のloopback bindがない'
docker inspect immich_server --format '{{range .Mounts}}{{if eq .Destination "/external/photo-library"}}{{.RW}}{{end}}{{end}}' | grep -Fxq false || die 'External Libraryがread-onlyではない'
docker exec immich_server sh -c 'test -r /external/photo-library && ! test -w /external/photo-library' || die 'コンテナからExternal Libraryのread-only性を確認できない'
if [[ "$REQUIRE_CUDA" == true ]]; then
  docker inspect immich_machine_learning --format '{{json .HostConfig.DeviceRequests}}' | grep -Fq nvidia || die 'GPUがmachine-learningへ割り当てられていない'
  docker exec immich_machine_learning python -c 'import onnxruntime as ort; assert "CUDAExecutionProvider" in ort.get_available_providers(); print(ort.get_available_providers())' >/dev/null || die 'CUDAExecutionProviderをコンテナ内で確認できない'
fi
if compgen -G "$IMMICH_ROOT/data/backups/*.sql.gz" >/dev/null; then
  dump=$(ls -t "$IMMICH_ROOT/data/backups"/*.sql.gz | head -n1)
  [[ -s "$dump" ]] && gzip -t "$dump" || die 'DBダンプが不正である'
  printf 'DBダンプ: %s\nサイズ: %s バイト\nSHA-256: %s\nImmich固定版: %s\n' \
    "$dump" "$(stat -c '%s' "$dump")" "$(sha256sum "$dump" | awk '{print $1}')" "$IMMICH_VERSION"
else printf '注意: DBダンプはまだ生成されていない。管理画面からCreate Database Dumpを実行すること。\n'; fi
printf 'OK: Immichの基本構成を確認した。\n'
