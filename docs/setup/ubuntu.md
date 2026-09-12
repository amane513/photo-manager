# Ubuntu常時稼働PCの構築手順

主HDDの接続と共有、Immich、第2 HDDへのバックアップを担当するホストの手順である。全体の流れは [README.md](README.md) を参照する。

## 前提

- Ubuntu 64-bitをインストール済みで、sudoを実行できるアカウントがある。
- 4TB主HDDを接続している。正本のルートは `/mnt/camera_archive` とする。
- Immichの作業データとPostgreSQLは内蔵SSDの `/srv/immich/` に置く。

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

### 4. 通常状態を検査する

```sh
sudo ./scripts/ubuntu/verify-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

この検査は、UUIDに対応するHDDが `/mnt/camera_archive` にマウントされ、fstab、所有者・権限、Sambaサービスが揃っていることを判定する。

### 5. MacからSMBを確認する

Finderで `smb://<UbuntuのIPアドレス>/CameraArchive` に接続し、`amane-yajima` で認証する。テストファイルを作成、開き、削除してUbuntu側でも反映を確認する。SMBはAmazon Photosと必要時のFinder・現像ツールからの参照用とし、取り込みCLIの転送には使わない。

### 6. 未マウント時の誤書込み防止を確認する

Macで共有を切断し、Ubuntuで開いているファイルがないことを確認してから実行する。この確認中は共有を使えない。

```sh
sudo umount /mnt/camera_archive
sudo ./scripts/ubuntu/verify-unmounted-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
sudo mount /mnt/camera_archive
sudo ./scripts/ubuntu/verify-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

未マウント時のマウントポイントがroot所有・0755であり、写真保存用アカウントが書き込めないことを確認する。検査が失敗した場合は再マウントせず原因を修正する。

### 7. コピー受信環境を整備する

rsync over SSHの受信に必要なrsyncと、撮影日時の確認に使うExifToolを導入する。Ubuntuではapt標準のrsync 3.2.6以上を前提とし、より新しい版への更新は行わない。現在の実機では3.2.7を確認している。

```sh
sudo ./scripts/ubuntu/setup-copy-receiver.sh --dry-run
sudo ./scripts/ubuntu/setup-copy-receiver.sh
```

スクリプトは不足する `rsync` と `libimage-exiftool-perl` だけを導入する。既に導入済みのパッケージを更新・再インストールしない。

### 8. コピー受信環境を検査する

```sh
sudo ./scripts/ubuntu/verify-copy-receiver.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

この検査は主HDDのUUID・マウント・写真保存アカウントの書込み権限、rsync、ExifToolを確認する。SSH鍵の登録と、Macからの接続確認は手動で行う。

`photo-copy` のrsync over SSH転送は実装済みである。Mac側から `photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env` を実行すると、転送を伴わずに接続ユーザー、主HDDのマウントとUUID、書込み可否、Mac側・リモート側のrsyncバージョンを検査できる。利用手順の正本は [mac.md](mac.md) である。Immichは0011、第2 HDDへのバックアップは0010で追加する。
