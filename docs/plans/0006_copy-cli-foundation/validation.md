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

## 2026-09-12: 第2段階（段階1〜5）の代表メディア・実機確認

SDカード（`CameraSD`、Sony α7C II由来）とMac、Ubuntu（`ubuntu`）の間で確認した。
コピー元（SDカード）は変更・削除せず、代表ファイルを`cp`でMac上の隔離した作業
ディレクトリへ複製してから使用した。主HDDへの転送は`/mnt/camera_archive/
photo-copy-test-*/`配下の隔離した試験先ディレクトリへ行い、確認後にすべて削除
した（既存の`/mnt/camera_archive/2026/2026-08/`など本番配置には触れていない）。
作業用の一時ファイル（`~/tmp/photo-copy-real-check/`、約3.3GB）と、確認のために
作成した`~/.config/photo-copy/profiles.ini`も、確認後にすべて削除した。

iPhone 13由来のHEIC/MOVとXMPサイドカーの確認は、実際にイメージキャプチャで
取り込む手順を再現しながら行いたいという方針により、今回は見送り0007で扱う。

### 1. 代表メディアでのタグ優先順位・組の基準ファイル判定（ARW/JPG/MP4）

SDカードの`DCIM/100MSDCF/DSC00305.ARW`+`.JPG`（ARW+JPGの組）、`DSC00241.JPG`
（単独JPG）、`PRIVATE/M4ROOT/CLIP/C0006.MP4`+`C0006M01.XML`（MP4+未対応形式の組）
を複製して`metadata.capture_timestamps`と`planning.build_plan`を直接呼び出した。

- ARW: `ExifIFD:DateTimeOriginal`（2026-08-23 19:15:59）を取得し、`20260823-191559`
  になった。同じ組のJPGにも同一の日時プレフィックスが適用された（ARWが基準ファイル
  として選ばれることを確認）。
- MP4: `DateTimeOriginal`が無く、`MediaCreateDate`（QuickTimeUTC変換後のローカル
  時刻）から`20260830-122104`になった。
- 単独JPG: `DateTimeOriginal`から`20260822-184717`になった。
- `C0006M01.XML`: 対応タグを持たず`None`になり、計画では「未対応の形式である」で
  未処理になった。
- `build_plan`（`--layout classify --device camera`）で、ARW+JPGは同一日時プレフィックス
  で`camera/`直下へ計画され、MP4は`MediaCreateDate`由来の日時で計画され、XMLは
  未処理になることを確認した。

HEIC、MOV（iPhone由来）、XMPサイドカーの確認は0007（イメージキャプチャでの
取り込み手順の再現）へ持ち越す。

### 2. 動画のTZ（decisions.mdの未決定事項の解消）

同じ`C0006.MP4`に異なる`TZ`を与えて`capture_timestamps`とExifTool生出力を比較した。

| TZ | 変換結果 |
|---|---|
| 未指定（実行ホスト、Asia/Tokyo相当） | 20260830-122104 |
| `Asia/Tokyo` | 20260830-122104 |
| `UTC` | 20260830-032104 |
| `America/Los_Angeles` | 20260829-202104（前日） |

QuickTimeの生の記録（`-api QuickTimeUTC=1`無し）は`2026:08:30 03:21:04`（オフセット
情報なし、UTC）であり、変換結果が`TZ`次第で変わることを実データで確認した。一方、
同じSDカードのARW/JPGは`ExifIFD:DateTimeOriginal`と`OffsetTimeOriginal`（`+09:00`）
を直接記録しており、実行環境のTZに依存しない。

この非対称性により、動画のTZを実行ホスト任せにすると、内容一致によるスキップの
前提（同じ配置先名になること）が実行環境によって崩れる恐れがあることを確認した。
`decisions.md`の2026-09-12「動画のTZは固定値（Asia/Tokyo）とする」で解消し、
`cli.py`の既定値を`DEFAULT_TIMEZONE = "Asia/Tokyo"`へ変更、回帰テスト2件
（`test_timezone_defaults_to_fixed_value_when_omitted`、
`test_explicit_timezone_overrides_default`）を追加した（自動テストは107件から109件）。

### 3. rsync over SSHの`facts()`/`digest()`の実機確認

Ubuntu標準のcoreutils（`wc -c`、`sha256sum`）とNUL区切りのやり取りで、想定どおりに
動作した。第1段階の`findmnt`のような実装依存の不具合は見つからなかった。

- 初回コピー（ARW/JPG/MP4の4ファイル）を`--transport rsync-ssh`で実行し、正しく
  配置されることを確認した。
- 同じ範囲を再実行し、4件とも`facts()`（サイズ一致）→`digest()`（SHA-256一致）で
  `skipped`になることを確認した（XMLは変わらず`unresolved`）。
- 単独JPGの1バイトだけを書き換えた同サイズのファイルを用意し、同じ配置先へ
  送ったところ、サイズが同じでもSHA-256が一致せず`conflict`（「同名で内容が異なる」）
  になることを確認した。

### 4. 既存ファイルが多い範囲の再実行時間

SDカードから実データのARW+JPG50組（100ファイル、計2.6GB）を複製し、Ubuntu上の
隔離した試験先へ`--transport rsync-ssh`で計測した。

| 実行 | 所要時間 | 結果 |
|---|---|---|
| 初回コピー | 7分24秒 | コピー済み100件 |
| 再実行（全件既存） | 5.35秒 | スキップ100件 |

初回は前回実測の実効転送速度（5.8 MB/s）に見合う結果だった。再実行は
ExifToolの一括呼び出し、リモートでの`facts()`/`digest()`（主HDD上の2.6GB分の
SHA-256計算を含む）、Mac側のSHA-256計算をすべて含めて5.35秒であり、内容一致
スキップが再送信より大幅に高速であることを実機で確認した。

### 5. `--profile`/`--profile-config`の実運用確認

`~/.config/photo-copy/profiles.ini`（確認後に削除）に、実際の
`scripts/hosts/ubuntu-amane-yajima.env`を指す`host-config`を含むプロファイルを
作成し、リポジトリルートから`photo-copy copy --profile sd-to-ubuntu`（dry-run→
実行）だけで、SDカードの`PRIVATE/M4ROOT/CLIP`配下のMP4 5件をUbuntuの隔離した
試験先へ実際に配置できることを確認した。詳細ログの`host_config`
（`scripts/hosts/ubuntu-amane-yajima.env`、カレントディレクトリ基準の相対パス
のまま記録される）、`timezone`（`Asia/Tokyo`）、`only`、`profile`名がいずれも
解決後の値として記録されることを確認した。5件は撮影年月が2026-08と2026-09に
分かれ、`--year-month`を指定しなくても自動分類されることもあわせて確認した。

運用上の注意点: `profiles.ini`はホスト固有の秘密情報を直接含まないが、`source`や
`destination-root`など環境依存のパスを含むため、ファイル権限を利用者専用
（`600`）にした。相対パスで書いた`host-config`はカレントディレクトリ基準で解決
されるため、手順書ではリポジトリルートから実行することを明記する必要がある
（`docs/setup/mac.md`更新時に反映）。

### 6. TransferAbortedの実機再現（第1段階から持ち越し）

大きめの実データ（`C0006.MP4`、約335MB）を含む3ファイルの転送を開始し、転送開始
15秒後に、同じ`ControlPath`（`/tmp/photo-copy-<uid>/cm-%C`、SSHの`%C`トークンに
より自動的に同じソケットへ解決される）に対して`ssh -O exit`を実行し、稼働中の
ControlMasterを強制的に切断した。

- 転送中のrsyncが`rsync: [sender] write error: Broken pipe (32)` / 終了コード255で
  失敗し、23/24以外のコードとして`TransferAborted`が正しく送出された。
- 転送中だったファイルは`failed`、残り2件は「転送中断のため未処理」で`unresolved`
  になった。構造化結果の`aborted`は`True`、`abort_reason`にrsyncの終了コードと
  メッセージが記録された。
- 試験先ディレクトリには、完成した最終名のファイルも、rsyncの一時ファイルも
  一切残らなかった（`find -type f`で0件）。空になった年月・機器ディレクトリだけ
  が残り、`rm -rf`で問題なく削除できた。

主HDDへ実害を与えずに、実際のSSH切断によるTransferAbortedを再現できることを
確認した。

### 7. `--only`と実機のSDカード構造の組み合わせ

SDカード（`/Volumes/CameraSD`）に対して`--dry-run --transport local`で確認した
（コピー元・コピー先とも変更しない）。

- `--only DCIM/100MSDCF`: 995件が計画された（ExifToolの一括呼び出しは約9秒）。
- `--only PRIVATE/M4ROOT/CLIP`: MP4 5件が計画され、対応するXML 5件が未対応形式
  として未処理になった。`PRIVATE/DATABASE`や`PRIVATE/M4ROOT/GENERAL`など
  範囲外のディレクトリは計画に現れなかった。
- `--only PRIVATE/M4ROOT/CLIP --only PRIVATE/M4ROOT/THMBNL`
  （複数指定）: 10件（MP4 5件+サムネイルJPG 5件）が計画され、重複や欠落は
  無かった。

実機のSDカードの実際の階層（`DCIM/`、`PRIVATE/DATABASE`、`PRIVATE/M4ROOT/{CLIP,
GENERAL,SUB,TAKE,THMBNL}`）に対しても、`--only`による絞り込みが単一・複数指定
とも想定どおりに機能することを確認した。

### 今回の実機確認で見つかった不具合

無し。第1段階の`findmnt`のような実装依存の不具合は今回は見つからなかった。

## 2026-09-12: iPhone 13由来のHEIC/MOVとXMPサイドカーの実機確認

iPhone 13を実際にMacへ接続し、イメージキャプチャで代表ファイルを取り込む手順を
再現しながら確認した。取り込み先はPhotoWork内の旧`PhotoInbox/current/`命名
（機器名+日付）を踏襲せず、PhotoWorkの外に置く一時置き場
`~/Pictures/PhoneImportInbox/iphone/`とした。理由は、proposal.md 4.1で
「PhotoWorkとHDDを同じ相対構成にする」と定めており、イメージキャプチャが吐く
未分類の生ファイルをPhotoWork直下に置くと分類済み構成の原則が崩れるため。
生ファイルはphoto-copyで分類した後にPhotoWorkへ入れ、置き場自体は空にする運用
とする。この置き場の設計はdocs/setup/mac.md反映時に取り込む。

イメージキャプチャの実機画面はメニュー・ボタンが英語表記であり、次の対応関係を
確認した（docs/setup/mac.md反映用のメモ）。

| 案内時の想定表記 | 実機での表記 |
|---|---|
| 読み込み先 | Import To: |
| その他... | Other... |
| 読み込む | Download |

取り込んだ代表ファイル（Live Photo＝`IMG_1527.HEIC`+`IMG_1527.MOV`の組、単独の
`IMG_1526.MOV`、単独の`IMG_1525.HEIC`）を、`~/Pictures/PhoneImportInbox/iphone/`
自体は変更せず`cp`で`~/tmp/photo-copy-iphone-check/`（隔離した作業ディレクトリ、
確認後に削除）へ複製してから使用した。

### 1. タグ優先順位と組の基準ファイル（HEIC/MOV）

`metadata.capture_timestamps`を直接呼び出した。

- `IMG_1525.HEIC`（単独）: `ExifIFD:DateTimeOriginal`から`20260912-153734`。
- `IMG_1526.MOV`（単独）: `DateTimeOriginal`が無く、`MediaCreateDate`
  （QuickTimeUTC変換後）から`20260912-153742`。
- `IMG_1527.HEIC`+`IMG_1527.MOV`（Live Photoの組）: 両方とも`20260912-153751`
  になった。HEIC単体の`DateTimeOriginal`（15:37:51.771）がそのままMOV側にも
  適用されており、`planning.REFERENCE_PRIORITY`（`.arw` > `.heic` > `.jpg`/
  `.jpeg` > `.mov` > `.mp4`）どおりHEICが基準ファイルとして選ばれることを
  実データで確認した。
- `planning.build_plan`（`--layout classify --device smartphone`）でも同じ結果
  になり、4件とも`smartphone/`直下へ計画された（HEIC基準での同一日時プレフィックス
  を確認）。

### 2. 動画のTZ（退行が無いことの確認）

`IMG_1526.MOV`の生のQuickTimeタグ（`-api QuickTimeUTC=1`無し）は`06:37:42`
（オフセット無し、UTC相当）であり、`TZ`を明示せず変換すると実行ホストのTZ次第で
結果が変わることをiPhone由来のMOVでも確認した（`TZ=UTC`では`20260912-063742`、
`TZ=Asia/Tokyo`または未指定でホストがJSTの場合は`20260912-153742`）。これは
Sony製MP4で確認済みの非対称性と同じであり、`decisions.md`の「動画のTZは固定値
（`Asia/Tokyo`）とする」で既に解消済みであることを確認した。新たな決定は不要
だった。

### 3. XMPサイドカー

このMac環境にはLightroomやCapture Oneは無く、darktable（5.6.0）のみ導入されて
いた。`darktable-cli`単体（スタイル未指定）では現像履歴が無くXMPが書き出されな
かったため、darktableのGUIで実際に`DSC00805.ARW`（SDカードの代表ARWを隔離した
作業ディレクトリへ複製したもの）を開き、露出モジュールを操作して現像履歴を作り、
実際の`DSC00805.ARW.xmp`を1件用意した。ARW自体もHEIC/MOVもコピー元は変更して
いない。

- 生成された`DSC00805.ARW.xmp`は`exif:DateTimeOriginal`と`darktable:history`
  などを含む、想定どおりの`<原名>.ARW.xmp`形式だった。
- `build_plan`（`--layout classify --device camera`）で、ARW+XMPの組は
  `planning.py`の`.arw.xmp`特例により同一の日時プレフィックス
  （`20260906-140415`）で`camera/`直下へ計画され、ARWが基準ファイルとして
  使われることを確認した（XMPは基準ファイルにしないという決定どおり）。
- 対応するARWが無い単独XMP（同じ内容を別名`DSC99999.ARW.xmp`として用意）は、
  `--year-month`省略時は「組の基準ファイルがない」で未処理（`UNRESOLVED`）に
  なり、`--year-month 2026-09`を明示すると原名のまま`camera/`直下へ配置される
  ことを確認した。基準ファイル判定・配置規則への影響は無かった。

### 4. rsync over SSHでの実配置

Ubuntu（`ubuntu`）の`/mnt/camera_archive/photo-copy-test-20260912155947/`
（試験後に削除）へ、HEIC/MOVの4件とARW+XMPの組を`--transport rsync-ssh`で
実際に配置した。

- HEIC/MOVの4件は`dry-run`で予定4件、実行で配置済み4件となり、
  `smartphone/`直下に想定どおりの名前で配置された。
- ARW+XMPの組は`camera/`直下に同一日時プレフィックスで配置された。
- 確認後、試験先ディレクトリを`ssh ubuntu "rm -rf ..."`で削除し、残存が無い
  ことを確認した。主HDDの既存配置（`2026/2026-08/`など）には触れていない。

### 今回の実機確認で見つかった不具合

無し。コード修正は行っていない（`.venv/bin/python -m unittest discover -s
tests`は引き続き109件成功）。

## 2026-09-12: インストール・設定・更新・確認スクリプトの実機再実行

0006の残作業として、既存のMac/Ubuntu向けスクリプトを実機で再実行し、コードの
進展（第2段階の実装、iPhoneの実機確認）を反映した状態でも冪等に動作すること
を確認した。

- Mac: `./scripts/mac/setup-copy-cli.sh --dry-run`→通常実行→
  `./scripts/mac/verify-copy-cli.sh`を実行した。ExifTool・venvは既存のまま
  再利用され、`pip install --editable`の再実行だけが行われた（`Successfully
  installed photo-copy-0.1.0`で上書き導入を確認）。verifyはPython 3.10、
  rsync 3.5.0、ExifTool 13.55、photo-copyを確認した。
- Ubuntu: リポジトリが旧コミット（`e26181d`）のままだったため`git pull
  --ff-only`で最新（`d299e2b`）へ更新してから、利用者が手元で
  `sudo ./scripts/ubuntu/setup-copy-receiver.sh --dry-run`→通常実行→
  `sudo ./scripts/ubuntu/verify-copy-receiver.sh --host-config
  ./scripts/hosts/ubuntu-amane-yajima.env`を実行した。sudoのパスワード入力が
  必要なため、非対話SSH（Claude側）では実行できず、利用者本人が実行した。
  rsync・ExifToolは導入済みのまま更新されず、verifyは主HDDのUUID一致、書込み
  権限、rsync 3.2.7、ExifTool 12.76を確認した。

いずれも「既存の設定やデータを無断で上書きしない」「再実行しても壊れない」
という`scripts/README.md`の実行規約どおりに動作した。

### 今回の実機確認で見つかった不具合

無し。

## 未確認事項（最新）

- [x] ARW、JPG、MP4の代表メディア（Sony α7C II由来の実データ）で、
      `metadata.capture_timestamps`が想定どおりのタグを返すこと、組の基準ファイル
      （ARW優先）が実データでも一意に決まることを2026-09-12に確認した。
- [x] HEIC、MOV（iPhone 13由来）、XMPサイドカーの実データ確認を、イメージキャプチャ
      での取り込み手順の再現とあわせて2026-09-12に行った。
- [x] 動画（MOV/MP4）の`TZ`は2026-09-12に固定値（`Asia/Tokyo`）とする決定で解消した
      （`decisions.md`参照）。
- [x] rsync over SSHの`facts()`/`digest()`が呼ぶリモートスクリプトは、Ubuntu標準の
      coreutilsで想定どおりに動作することを2026-09-12に確認した。
- [x] 既存ファイルが多い範囲（100ファイル、2.6GB）の再実行時間を2026-09-12に実測した
      （初回7分24秒→再実行5.35秒）。
- [x] `--profile`/`--profile-config`を実際の`scripts/hosts/*.env`と組み合わせた実運用を
      2026-09-12に確認した。
- [x] （第1段階から持ち越し）TransferAborted相当のSSH切断を、主HDDへ実害を与えない
      方法（ControlMasterの強制切断）で2026-09-12に実機再現した。
- [x] （第1段階から持ち越し）`--only`と実機のSDカード構造（`DCIM/`・`PRIVATE/`の実際の
      階層）の組み合わせを2026-09-12に確認した。

HEIC/MOV（iPhone由来）/XMPを含め、0006の実機確認事項はすべて完了した。残る
未着手はインストール・設定・更新・確認のスクリプト整備と、`docs/setup/mac.md`・
`docs/setup/ubuntu.md`・`scripts/`の更新のみである。0007（代表メディアでの
配置・閲覧確認）は、今回確認したイメージキャプチャの取り込み手順を引き継いで
開始できる。
