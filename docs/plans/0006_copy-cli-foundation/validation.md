# 0006 検証記録

## 2026-09-11: MacのコピーCLI実行環境

- `scripts/mac/setup-copy-cli.sh --dry-run` を実行した。
- `scripts/mac/verify-copy-cli.sh` を実行し、Python 3.10、Homebrew rsync 3.5.0、ExifTool 13.55、プロジェクトvenv内の `photo-copy` を確認した。
- Pythonの自動テスト5件が成功した。

## 2026-09-11: Ubuntuのコピー受信環境

- `scripts/ubuntu/setup-copy-receiver.sh --dry-run` と通常実行を行った。
- `scripts/ubuntu/verify-copy-receiver.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env` が成功した。
- 主HDDのUUID `0574e6d5-893c-41b5-84e8-77c41c3b59c1`、写真保存アカウントの書込み権限を確認した。
- rsyncは3.2.7（protocol 31）、ExifToolは12.76であった。

## 未確認事項

- MacからUbuntuへのSSH経由の実ファイル転送、主HDD切断時の中断、一時ファイル処理は、コピー本体の実装後に隔離した試験先で確認する。
- ARW、JPEG、HEIC、MOV、XMPの実データから撮影日時を取得し、組ファイルへ同じプレフィックスを付けられるかは未確認である。
