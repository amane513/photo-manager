# 環境構築スクリプト

環境構築を自動化したスクリプトを置く。実行順と前提、自動化できない操作は [docs/setup/](../docs/setup/) を参照する。取り込みCLIなどのアプリケーションコードはここに置かない。

## 構成

```text
scripts/
├── lib/        # ログ、確認、共通関数
├── ubuntu/     # 常時稼働PC向け
├── mac/        # MacBook Air向け
└── hosts/      # ホスト固有の値（*.env）
```

## 実行規約

- 冪等とする。再実行しても既存の設定やデータを壊さない。
- `--dry-run` を備え、変更内容を事前に確認できるようにする。
- 既存の設定ファイルやデータを無断で上書きしない。変更前の内容を退避するか、差分を示して確認を求める。
- 失敗を成功として扱わない。`set -euo pipefail` を基本とし、途中で失敗した場合は明示して終了する。
- 完了条件の判定は `verify-*.sh` に分け、構築スクリプトとは独立して実行できるようにする。
- 実機で実行していないスクリプトを完成として扱わない。

## ホスト固有の値

HDDのUUID、マウント先、共有名、利用アカウントなどは `hosts/<host-name>.env` に置き、スクリプトへ直書きしない。スクリプトは対象ホストのファイルを読み込んで動作する。

パスワード等の秘密情報はコミットせず、実行時に入力する。

## 0005: 主HDDとSMB共有

Ubuntuでは次の順に実行する。実行には対象ホスト上でのsudo認証が必要である。

```sh
sudo ./scripts/ubuntu/setup-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run

sudo ./scripts/ubuntu/setup-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --adopt-existing-share

sudo ./scripts/ubuntu/verify-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

`--adopt-existing-share` は、手動で作成済みの同名共有を初めてこのスクリプトの管理へ移す場合だけ指定する。設定変更前に `/etc/fstab` と `/etc/samba/smb.conf` の日時付きバックアップを作る。既存のマウント定義や共有と値が競合する場合は停止し、無断で置き換えない。

`verify-unmounted-primary-storage.sh` は、通常検証と分けて、HDDを安全にアンマウントした直後だけ実行する。詳細な実行順は [docs/setup/ubuntu.md](../docs/setup/ubuntu.md) を参照する。
