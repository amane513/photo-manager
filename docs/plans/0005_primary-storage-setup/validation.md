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

## 未完了の検証

sudo認証が必要なため、構築スクリプトの実行、fstabとSamba設定の内容確認、未マウント時の書込み拒否は未実施である。`docs/setup/ubuntu.md` の手順4〜6を実行後、この記録に実行日時と結果を追記する。
