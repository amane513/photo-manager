#!/usr/bin/env bash
# ImmichのSSD配置とCompose定義を安全に準備し、CPU/CUDAの明示的な起動を行う。
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/../lib/common.sh"
REPO_DIR=$(cd -- "$SCRIPT_DIR/../.." && pwd)
DRY_RUN=false; CONFIG_PATH=; MODE=prepare; UPDATE_CONFIG=false
while (($#)); do
  case "$1" in
    --host-config) CONFIG_PATH=${2:?}; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --cpu-smoke) MODE=cpu; shift ;;
    --cuda) MODE=cuda; shift ;;
    --update-config) UPDATE_CONFIG=true; shift ;;
    -h|--help) printf '使い方: sudo setup-immich.sh --host-config FILE [--dry-run] [--cpu-smoke|--cuda] [--update-config]\n'; exit 0 ;;
    *) die "不明な引数: $1" ;;
  esac
done
[[ -n "$CONFIG_PATH" ]] || die '--host-config を指定すること'
load_host_config "$CONFIG_PATH"; require_root
for name in IMMICH_ROOT IMMICH_LAN_BIND_ADDRESS IMMICH_PORT IMMICH_VERSION ARCHIVE_LIBRARY_ROOT; do [[ -n "${!name:-}" ]] || die "ホスト設定に $name がない"; done
[[ "$IMMICH_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'IMMICH_VERSIONは完全な安定版番号にすること'
[[ "$IMMICH_PORT" =~ ^[0-9]+$ ]] || die 'IMMICH_PORTが不正である'
[[ ! -L "$ARCHIVE_LIBRARY_ROOT" && -d "$ARCHIVE_LIBRARY_ROOT" ]] || die '主HDDのライブラリルートがない、またはシンボリックリンクである'
mountpoint -q "$ARCHIVE_MOUNT" || die '主HDDが未マウントのため起動しない'
expected=$(blkid -U "$PRIMARY_STORAGE_UUID") || die '主HDD UUIDが見つからない'
[[ $(findmnt -no SOURCE "$ARCHIVE_MOUNT") == "$expected" ]] || die '主HDDのマウント元が想定と違う'

app="$IMMICH_ROOT/app"; source_dir="$REPO_DIR/scripts/ubuntu/immich"
for dir in "$IMMICH_ROOT" "$app" "$IMMICH_ROOT/data" "$IMMICH_ROOT/postgres" "$IMMICH_ROOT/model-cache"; do run install -d -o root -g root -m 0755 "$dir"; done
for file in docker-compose.yml compose.ml-cuda.yml hwaccel.ml.yml; do
  target="$app/$file"; source_file="$source_dir/$file"
  if [[ -e "$target" ]] && ! cmp -s "$source_file" "$target"; then
    [[ "$UPDATE_CONFIG" == true ]] || die "既存設定がリポジトリ版と異なる: $target。確認後に--update-configを指定すること"
    run cp -a "$target" "$target.$(date +%Y%m%d%H%M%S).bak"
  fi
  if [[ ! -e "$target" || "$UPDATE_CONFIG" == true ]]; then run install -o root -g root -m 0644 "$source_file" "$target"; fi
done
env_file="$app/.env"
if [[ ! -e "$env_file" ]]; then
  if [[ "$DRY_RUN" == true ]]; then
    printf '+ root所有・0600の %s を対話入力したDBパスワードで作成\n' "$env_file"
  else
  read -r -s -p 'Immich PostgreSQLパスワード（英数字のみ）: ' db_password; printf '\n'
  [[ "$db_password" =~ ^[A-Za-z0-9]{16,}$ ]] || die 'DBパスワードは16文字以上の英数字にすること'
  umask 077
  { printf 'UPLOAD_LOCATION=%s\nDB_DATA_LOCATION=%s\nMODEL_CACHE_LOCATION=%s\nARCHIVE_LIBRARY_ROOT=%s\nIMMICH_LAN_BIND_ADDRESS=%s\nIMMICH_PORT=%s\nIMMICH_VERSION=%s\nTZ=Asia/Tokyo\nMACHINE_LEARNING_WORKERS=1\nMACHINE_LEARNING_DEVICE_IDS=0\nDB_PASSWORD=%s\nDB_USERNAME=postgres\nDB_DATABASE_NAME=immich\n' "$IMMICH_ROOT/data" "$IMMICH_ROOT/postgres" "$IMMICH_ROOT/model-cache" "$ARCHIVE_LIBRARY_ROOT" "$IMMICH_LAN_BIND_ADDRESS" "$IMMICH_PORT" "$IMMICH_VERSION" "$db_password"; } > "$env_file"
  chown root:root "$env_file"; chmod 0600 "$env_file"
  fi
else
  [[ $(stat -c '%U:%G:%a' "$env_file") == root:root:600 ]] || die '.envの所有者または権限が安全でない'
fi
[[ "$DRY_RUN" == true ]] && { printf 'dry-run完了: ファイル作成、秘密値入力、コンテナ操作は行っていない。\n'; exit 0; }
[[ "$MODE" == prepare ]] && { printf '準備完了: %s。CPU確認は--cpu-smoke、通常のCUDA起動は--cudaを使う。\n' "$IMMICH_ROOT"; exit 0; }
require_command docker
args=(-f "$app/docker-compose.yml")
[[ "$MODE" == cuda ]] && args+=(-f "$app/compose.ml-cuda.yml")
run docker compose --project-directory "$app" "${args[@]}" config --quiet
run docker compose --project-directory "$app" "${args[@]}" pull
run docker compose --project-directory "$app" "${args[@]}" up -d
printf '%s構成を起動した。verify-immich.shで検査すること。\n' "$MODE"
