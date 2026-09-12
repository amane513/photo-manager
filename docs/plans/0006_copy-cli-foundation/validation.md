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

## 2026-09-12: rsync over SSH転送層と配置モードの実機確認（第1段階）

MacとUbuntu（`ubuntu`）の間で、`/mnt/camera_archive/photo-copy-test-20260912113048/`（試験後に削除）を
配置先として実行した。実データや既存の配置（`/mnt/camera_archive/2026/2026-08/`）には触れていない。

- `.venv/bin/python -m unittest discover -s tests` で58件が成功した（転送層分離、`--layout`両モード、
  形の検査、除外区分、hosts.py、rsync.pyをフェイクのsubprocess.run注入で確認）。
- `photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env` が成功し、Mac側rsync 3.5.0、
  リモートrsync 3.2.7、主HDDのUUID一致を確認した（C05）。
- 実装当初、`findmnt -n -o UUID --target -- "$path"` が起動中のfindmnt（util-linux、Ubuntu標準）で
  「--targetと--sourceはコマンドライン要素と併用できない」エラーになる不具合を実機で発見した。
  `--target`の引数の前に`--`（オプション終端）を置かないよう`rsync.py`を修正した。ユニットテストの
  フェイクはコマンドの構造しか見ておらず、この不具合を検出できなかった。
- `--layout classify --transport rsync-ssh`で、DateTimeOriginalを書き込んだ試験用JPEGを
  `<配置先>/2026/2026-09/camera/20260911-143052_DSC00001.JPG`へ実際に配置できた（C01）。
  dry-runでは配置先に何も作られないことを確認した（C02）。コピー元は変更されなかった（C03）。
  再実行では既存ファイルを`existing()`のSSH確認で検出し、上書きせず衝突として報告した（C04）。
- `--layout preserve --transport rsync-ssh`で、既存の相対配置（`2026/2026-09/{camera,smartphone}/名前`）
  を維持したまま2件を配置し、4階層でない`loose-file.jpg`を未処理として報告した（C15、C16の一方向）。
- 読み取り不能な試験ファイル（`chmod 000`）を送ると、rsyncが終了コード23を返し、個別失敗として
  構造化結果に記録された。他のファイルへの影響はない（C06の個別失敗側）。詳細ログに
  `rsync_versions`（Mac側・リモート側）が記録されることも確認した（C08）。
- `PRIMARY_STORAGE_UUID`を誤らせたホスト設定、`ARCHIVE_MOUNT`配下にない`--destination-root`、
  存在しない`--destination-root`を、いずれも転送前に検出し実行不能（終了コード2）にした（C05）。
  `--destination-root`が`ARCHIVE_MOUNT`配下にない場合はSSHへ接続する前にMac側だけで検出する。
- ControlMasterのソケットは`/tmp/photo-copy-<uid>/cm-%C`に作られ、パーミッションが0700であること、
  `close()`（`ssh -O exit`）で確実に破棄されることを確認した（ディレクトリが空になることで確認）。
- ローカル転送（経路b相当）も同じCLIで実行し、`--transport local`で配置できることを確認した。

### 今回確認できなかったこと

- 転送中にSSH接続そのものが切断する中断（`TransferAborted`、終了コード1、23/24以外のrsync終了コード）は、
  ユニットテスト（`tests/test_rsync.py`、`tests/test_transfer.py`）のフェイク注入でのみ確認した。
  実機で意図的に接続を切る試験は、主HDDへの実害を避けるため今回は行っていない。
- ARW、HEIC、MOV、XMPなど組ファイルの実データからの撮影日時取得は0007で確認する（未対応）。
- `--only`と実機のSDカード構造（`DCIM/`・`PRIVATE/`の実際の階層）との組み合わせは未確認である。

## 未確認事項

- 中断（`TransferAborted`）相当のSSH切断を実機で起こす試験、`--only`と実際のSDカード構造の組み合わせは、
  0007以降でリスクの小さい方法を検討してから行う。
- ARW、JPEG、HEIC、MOV、XMPの実データから撮影日時を取得し、組ファイルへ同じプレフィックスを付けられるかは未確認である。

## 2026-09-12: 第2段階（段階1〜5）は自動テストのみで実装した。実機確認は未着手

段階1〜5（撮影日時の一括取得・妥当性検査、`--year-month`省略時の自動分類、
`facts()`/`digest()`によるサイズ+SHA-256の内容一致スキップ、再実行の安全性、
プロファイル設定）はすべて`.venv/bin/python -m unittest discover -s tests`
（107件、フェイク注入によるユニットテストのみ）で確認した実装であり、
代表メディアや実機のUbuntu受信環境には一切触れていない。次の各点は
実行していない確認であり、完了として扱わない。

- ARW、HEIC、MOV、XMPの代表メディアで、`metadata.capture_timestamps`が
  想定どおりのタグ（`DateTimeOriginal`→`MediaCreateDate`→`CreateDate`→
  `TrackCreateDate`）を返すか、組の基準ファイル（`.arw`>`.heic`>`.jpg`/`.jpeg`
  >`.mov`>`.mp4`）が実データのファイル名・拡張子でも一意に決まるか。
- 動画（MOV/MP4）の`TZ`を固定値にするか実行ホストに任せるかは、
  decisions.mdの未決定事項のままである。代表メディアでQuickTimeUTCの
  変換結果を確認してから決める。
- rsync over SSHの`facts()`/`digest()`が呼ぶリモートスクリプト
  （`wc -c`、`sha256sum`、NUL区切りの`値\0パス\0`のやり取り）が、
  Ubuntu標準のcoreutilsで実際に想定どおりの出力になるか。第1段階の
  `findmnt`のように、フェイクが検出できない実装依存の不具合が
  ある可能性がある。
- 既存ファイルが多い範囲を`--layout classify`（省略した`--year-month`による
  自動分類）や`--profile`で再実行した場合の、実際の所要時間（ExifToolの
  一括呼び出し時間、リモートでのSHA-256計算時間、主HDDの読み出し時間）。
- `--profile`/`--profile-config`を実際の`scripts/hosts/*.env`と組み合わせて
  日常のコマンドを短縮できるか、`~/.config/photo-copy/profiles.ini`の
  配置・パーミッションに関する実運用上の注意点。

これらは0007（代表メディアでの配置・閲覧確認）と、その後の実機確認で扱う。
