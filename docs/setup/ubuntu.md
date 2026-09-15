# Ubuntu常時稼働PCの構築手順

主HDDの接続と共有、Immich、第2 HDDへのバックアップを担当するホストの手順である。全体の流れは [README.md](README.md) を参照する。

## 前提

- Ubuntu 64-bitをインストール済みで、sudoを実行できるアカウントがある。
- 4TB主HDDを接続している。マウント先は `/mnt/camera_archive` とする。正本のライブラリルート（年フォルダを置く場所）はその1階層下の `/mnt/camera_archive/photo-library/` である。Amazon Photos Desktopがマウント直下のボリューム自体を対象にできず1つ下のフォルダしか指定できないため、年フォルダを直下に置かずライブラリルートを新設している（0008、[proposal.md](../proposal.md) 4.1）。
- Immichの作業データとPostgreSQLは内蔵SSDの `/srv/immich/` に置く。
- iPhoneからLAN外で閲覧する場合は、UbuntuとiPhoneを同じTailscaleのtailnetへ参加させる。

## 手動で行う作業

- 主HDDと第2 HDDの物理的な接続。
- 新しいHDDを使う場合のフォーマット判断。既存のデータがあるHDDを自動でフォーマットしない。

## 手順

### 1. ホスト設定を確認する

リポジトリ上の [`scripts/hosts/ubuntu-amane-yajima.env`](../../scripts/hosts/ubuntu-amane-yajima.env) は、現在の常時稼働PCで確認した値である。別のPCを構築する場合は [`scripts/hosts/ubuntu.env.example`](../../scripts/hosts/ubuntu.env.example) をコピーし、実機で確認したUUID等に置き換える。

```sh
lsblk -f
id
```

UUID、ファイルシステム、利用アカウント、共有名を設定する。パスワードは設定ファイルに書かない。

### 2. Sambaの利用者を登録する

Sambaのパスワードはリポジトリやホスト設定へ保存しない。新しいUbuntu環境では、利用者を対話的に登録する。既存利用者の場合も、このコマンドで必要に応じてパスワードを再設定できる。

```sh
sudo smbpasswd -a amane-yajima
```

### 3. dry-runを確認して構築する

Ubuntuでリポジトリのルートへ移動して実行する。`--dry-run` の出力で、対象デバイス、fstab、共有名が意図どおりか確認してから実行する。

```sh
sudo ./scripts/ubuntu/setup-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run

sudo ./scripts/ubuntu/setup-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

既に同名のSamba共有を手動で作成している場合、通常実行は停止する。内容を確認して移行すると決めた場合だけ、次のように明示指定する。この操作では既存の `smb.conf` を日時付きで退避してから、対象共有だけをスクリプト管理の設定へ置き換える。

```sh
sudo ./scripts/ubuntu/setup-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --adopt-existing-share
```

スクリプトはHDDをフォーマットしない。`/etc/fstab` に別のマウント定義がある場合や、共有名が競合する場合も停止するので、内容を確認してから移行する。

### 4. ライブラリルートを作成する

年フォルダを置く正本のライブラリルート（`ARCHIVE_LIBRARY_ROOT`、既定 `/mnt/camera_archive/photo-library`）を、写真保存用アカウントの所有・0755で作成する。冪等であり、既に作成済みの場合は何もしない。

```sh
sudo ./scripts/ubuntu/setup-library-root.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run

sudo ./scripts/ubuntu/setup-library-root.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

### 5. 通常状態を検査する

```sh
sudo ./scripts/ubuntu/verify-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

この検査は、UUIDに対応するHDDが `/mnt/camera_archive` にマウントされ、fstab、所有者・権限、Sambaサービス、そしてライブラリルート（`ARCHIVE_LIBRARY_ROOT`）の存在・所有者・権限が揃っていることを判定する。

### 6. MacからSMBを確認する

Finderで `smb://<UbuntuのIPアドレス>/CameraArchive` に接続し、`amane-yajima` で認証する。`photo-library/` の下にテストファイルを作成、開き、削除してUbuntu側でも反映を確認する。SMBはAmazon Photosと必要時のFinder・現像ツールからの参照用とし、取り込みCLIの転送には使わない。

### 7. 未マウント時の誤書込み防止を確認する

Macで共有を切断し、Ubuntuで開いているファイルがないことを確認してから実行する。この確認中は共有を使えない。稼働中のsmbdワーカーがマウントを掴んでいて `umount` が `target is busy` になる場合は、`sudo lsof +D /mnt/camera_archive` で該当プロセスを特定し、Mac側が既に切断済みであることを確認したうえで終了させてから再試行する。

```sh
sudo umount /mnt/camera_archive
sudo ./scripts/ubuntu/verify-unmounted-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
sudo mount /mnt/camera_archive
sudo ./scripts/ubuntu/verify-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

未マウント時のマウントポイントがroot所有・0755であり、写真保存用アカウントが書き込めないこと、そしてライブラリルート（`ARCHIVE_LIBRARY_ROOT`）が存在しないことを確認する。検査が失敗した場合は再マウントせず原因を修正する。

### 8. コピー受信環境を整備する

rsync over SSHの受信に必要なrsyncと、撮影日時の確認に使うExifToolを導入する。Ubuntuではapt標準のrsync 3.2.6以上を前提とし、より新しい版への更新は行わない。現在の実機では3.2.7を確認している。

```sh
sudo ./scripts/ubuntu/setup-copy-receiver.sh --dry-run
sudo ./scripts/ubuntu/setup-copy-receiver.sh
```

スクリプトは不足する `rsync` と `libimage-exiftool-perl` だけを導入する。既に導入済みのパッケージを更新・再インストールしない。

### 9. コピー受信環境を検査する

```sh
sudo ./scripts/ubuntu/verify-copy-receiver.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

この検査は主HDDのUUID・マウント・写真保存アカウントの書込み権限、rsync、ExifToolを確認する。SSH鍵の登録と、Macからの接続確認は手動で行う。

`photo-copy` のrsync over SSH転送は実装済みである。Mac側から `photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env` を実行すると、転送を伴わずに接続ユーザー、主HDDのマウントとUUID、書込み可否、Mac側・リモート側のrsyncバージョンを検査できる。再実行時の内容一致スキップ（同名候補のSHA-256比較）は、Ubuntu標準のcoreutils（`sha256sum` 等）で行うため、追加の導入は不要である。利用手順の正本は [mac.md](mac.md) である。

### 10. Immichを導入する

Immichは `v3.2.0` に固定し、派生データを内蔵SSDの `/srv/immich/` に置く。主HDDの原本はコンテナ内の `/external/photo-library` にread-onlyで提供する。先に状態を確認する。

```sh
./scripts/ubuntu/inspect-immich-host.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env
sudo ./scripts/ubuntu/setup-immich-runtime.sh
sudo ./scripts/ubuntu/setup-immich.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env --dry-run
```

ランタイムがすべて揃っていることを確認後、次を実行する。初回だけDBパスワード（16文字以上の英数字）を端末へ入力する。これは `/srv/immich/app/.env` にroot所有・0600で保存され、リポジトリへ保存されない。

```sh
sudo ./scripts/ubuntu/setup-immich.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env
sudo ./scripts/ubuntu/setup-immich.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env --cpu-smoke
sudo ./scripts/ubuntu/verify-immich.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env
sudo ./scripts/ubuntu/setup-immich.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env --cuda
```

CUDA起動後、`sudo ./scripts/ubuntu/verify-immich.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env --require-cuda` を実行する。CPUへ一時的に戻す場合は `docker compose --project-directory /srv/immich/app -f /srv/immich/app/docker-compose.yml up -d` を使う。DB、`data/`、モデルキャッシュは削除しない。

ブラウザで `http://192.168.11.17:2283` を開き、初期管理ユーザーを作成する。次に管理画面でSmart Searchモデルを `XLM-Roberta-Large-ViT-H-14__frozen_laion5b_s13b_b90k` へ変更し、所有者をこの管理ユーザーとしてExternal Library `photo-library` を作成する。import pathは `/external/photo-library`、除外パターンは `**/*.ARW` と `**/*.arw` にする。設定後にスキャンとSmart Searchを開始する。

完了後、管理画面のJob Queuesから `Create Database Dump` を実行する。`verify-immich.sh` は `/srv/immich/data/backups/` の最新`.sql.gz`をgzip検査する。初回管理ユーザー、検索評価、DBダンプ生成は秘密情報または実データを伴うため手動で行う。ダンプは0013で第2 HDDへバックアップして実復元を確認するまで、同じSSD上にしかない。

### 11. iPhoneからTailscale経由でImmichを開く

ルーターのポート開放やTailscale Funnelは使わない。家庭内LAN向けの `http://192.168.11.17:2283` は維持し、Tailscale Serve用として同じImmichを `127.0.0.1:2283` にもbindする。

まず更新後のCompose定義を日時付きバックアップ付きで反映し、CUDA構成を再作成する。データベース、写真、サムネイルは削除しない。

```sh
sudo ./scripts/ubuntu/setup-immich.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run --update-config

sudo ./scripts/ubuntu/setup-immich.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --cuda --update-config

sudo ./scripts/ubuntu/verify-immich.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --require-cuda
```

次にTailscaleを構成する。初回は `--install-missing` を付ける。スクリプトはTailscale公式インストーラーを一時ファイルへ取得して実行し、Ubuntuが未認証の場合だけ `tailscale up` のログインURLを表示する。iPhoneで使うものと同じTailscaleアカウントで認証する。既に導入・認証済みなら再利用する。

```sh
sudo ./scripts/ubuntu/setup-tailscale-immich.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run --install-missing

sudo ./scripts/ubuntu/setup-tailscale-immich.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --install-missing

sudo ./scripts/ubuntu/verify-tailscale-immich.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

初回の `tailscale serve` 実行時にHTTPSの有効化を求められた場合は、表示されたTailscaleの確認ページで有効化する。スクリプト末尾の状態表示にある `https://<Ubuntu名>.<tailnet名>.ts.net` が接続先である。

iPhoneでは次を行う。

1. App StoreからTailscaleを導入し、Ubuntuと同じtailnetへログインしてVPN構成を許可する。
2. Wi-Fiを切ってモバイル回線にし、Safariで上記HTTPS URLを開いてImmichのログイン画面を確認する。
3. ImmichアプリのServer Endpoint URLにも同じHTTPS URLを入力し、既存のImmichユーザーでログインする。
4. Tailscaleを切るとHTTPS URLへ接続できず、再び有効にすると閲覧できることを確認する。

Immichアプリで接続先を変更した後もCurrent Server Addressに家庭内LANのIPが残る場合や、高解像度画像だけを取得できない場合は、アプリを完全に終了して再起動する。0025の実機確認では再起動後にTailscale URLが適用され、高解像度画像まで表示できた。

Serveはtailnet内だけに公開される。公開状態の停止はUbuntuで `sudo tailscale serve off` を実行する。iPhoneを紛失した場合は、Tailscaleの管理画面から当該端末を削除する。
