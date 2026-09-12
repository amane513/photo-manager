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

## 2026-09-11: ローカルコピー基盤の自動テスト

- `.venv/bin/python -m unittest discover -s tests -v` を実行し、13件が成功した。
- 一時ディレクトリだけを使い、撮影日時プレフィックス付きの配置、dry-runでの保存先不変更、コピー元保持、既存保存先との衝突、入力内の配置名衝突を確認した。
- ARWを基準にRAW/JPEG/XMPへ同じ日時を適用すること、基準不能な組と未対応形式を未処理として構造化結果・JSONログへ記録することを確認した。
- rsync over SSH、主HDD未マウント、転送中断、実データのメタデータは未確認である。

## 2026-09-12: rsync over SSHの実測（設計判断のための計測）

MacとUbuntu（`ubuntu`、192.168.11.17）の間で計測した。計測にはリモートの `/tmp` に作った一時ディレクトリと乱数ファイルだけを使い、主HDDには触れていない。計測後に両側の一時ファイルを削除した。

- rsyncはMac側3.5.0（protocol 32）、Ubuntu側3.2.7（protocol 31）であった。
- SSHハンドシェイクは多重化なしで0.36秒/回、ControlMaster多重化で0.035秒/回であった（各20回）。
- rsyncをファイルごとに呼ぶ場合の固定費は、多重化ありで0.148秒/ファイル、多重化なしで0.434秒/ファイルであった（各50ファイル）。
- rsyncを一括で呼ぶ場合の固定費は0.0034秒/ファイルであった（50ファイル）。
- 実効転送速度は5.8 MB/s（300MBを51.5秒）であった。素のSSHパイプでも6.6 MB/sであり、現在の無線リンクが律速している。
- 保存先ディレクトリが存在しない場合の終了コードは3、コピー元が読めない場合は23であった。
- `--ignore-existing` で既存ファイルをスキップした場合、終了コードは0かつ出力が空になり、既存ファイルの内容は変わらなかった。

この計測に基づき、ファイルごとのrsync呼び出しとSSH多重化を採用した。詳細は `decisions.md` に記録した。

## 未確認事項

- MacからUbuntuへのSSH経由の実ファイル転送、主HDD切断時の中断、一時ファイル処理は、コピー本体の実装後に隔離した試験先で確認する。
- ARW、JPEG、HEIC、MOV、XMPの実データから撮影日時を取得し、組ファイルへ同じプレフィックスを付けられるかは未確認である。
