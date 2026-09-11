# 0005 検証記録

作成日: 2026-09-11

## 実機の初期確認

Ubuntuホスト `amane-yajima-MS-7D32` で、次を読み取り確認した。

| 項目 | 確認値 |
|---|---|
| 主HDDデバイス | `/dev/sda1` |
| ファイルシステム | ext4 |
| ラベル | `CameraArchive` |
| UUID | `0574e6d5-893c-41b5-84e8-77c41c3b59c1` |
| 容量・空き | 3.6 TiB・3.4 TiB |
| マウント先 | `/mnt/camera_archive` |
| 保存用アカウント | `amane-yajima` |
| 通常時の所有者・権限 | `amane-yajima:amane-yajima`、0755 |
| SMB共有名 | `CameraArchive` |

既存の手動設定では、Macから `CameraArchive` へ接続してファイルの作成、読み出し、削除ができることをユーザーが確認済みである。

## 構築適用後の確認

2026-09-11 17:16（JST）に、Ubuntuホスト上で次を実行して成功した。

```sh
sudo ./scripts/ubuntu/setup-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --adopt-existing-share
```

適用後に読み取り確認した結果は次のとおりである。

| 項目 | 結果 |
|---|---|
| マウント | `/dev/sda1` が `/mnt/camera_archive` にext4としてマウント済み |
| fstab | `UUID=0574e6d5-893c-41b5-84e8-77c41c3b59c1 /mnt/camera_archive ext4 defaults,nofail 0 2` |
| マウント先の所有者・権限 | `amane-yajima:amane-yajima`、0755 |
| Samba共有 | `CameraArchive`、パス `/mnt/camera_archive`、書込み可、利用者 `amane-yajima` |
| Sambaサービス | `smbd` がactive |

既存のfstab行はスクリプトが無断変更せず、そのまま再利用した。既存の手動共有は日時付きバックアップを作成したうえで、`photo-manager` 管理ブロックへ移行した。

## 未完了の検証

## 未マウント時の誤書込み防止

2026-09-11 17:19（JST）に、MacのSMB接続をすべて切断した後、次を順に実行して成功した。

```sh
sudo systemctl stop smbd
sudo umount /mnt/camera_archive
sudo ./scripts/ubuntu/verify-unmounted-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
sudo mount /mnt/camera_archive
sudo systemctl start smbd
sudo ./scripts/ubuntu/verify-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

未マウント時は、`/mnt/camera_archive` が保存用アカウント `amane-yajima` による書込みを拒否した。再マウント後は、主HDD、fstab、権限、Sambaサービスの通常状態検査にも成功した。

## 再起動後の固定マウント確認

2026-09-11にUbuntuを再起動した後、次の通常状態検査が成功したことをユーザーが確認した。

```sh
sudo ./scripts/ubuntu/verify-primary-storage.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

これにより、fstabによる `/mnt/camera_archive` への固定マウント、権限、Sambaサービスと共有の復帰を確認した。
