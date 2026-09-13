# Macの構築手順

SDカードとiPhoneからの取り込み、必要時の選別・現像、Amazon Photosへのバックアップを担当するホストの手順である。全体の流れは [README.md](README.md) を参照する。

## 前提

- UbuntuへSSH接続でき、Ubuntu側の主HDDとSMB共有が利用できる（[ubuntu.md](ubuntu.md)）。
- 作業フォルダは `~/Pictures/PhotoWork/` の1つとする。HDDと同じ年月・機器別の分類済み構成だけを置く。
- iPhoneの取り込み用に `~/Pictures/PhoneImportInbox/<機器名>/` を一時置き場として使う（手順6）。

## 手動で行う作業

- Amazon Photos Desktopのインストール、ログイン、バックアップ対象フォルダの指定（手順9）。
- 現像ツールのライセンスやアカウントが必要な場合の初回設定。
- iPhoneを初めてこのMacへ接続したときに、iPhone側で「このコンピュータを信頼しますか？」を許可する。
- SMB共有のパスワードをキーチェーンへ保存する初回のFinder接続（手順8）。

## 手順

### 1. 外部で管理するrsyncを確認する

rsyncはdotfilesで管理する。Homebrew版のrsync 3系がPATHから検出できることを確認する。photo-managerのスクリプトはrsyncを導入・更新しない。

```sh
command -v rsync
rsync --version
```

### 2. dry-runを確認してコピーCLIを導入する

ExifToolはphoto-managerの構築対象である。スクリプトはExifToolがなければHomebrewで導入するが、既存のExifToolを更新・再インストールしない。Python 3.10以上の `.venv/` を作り、CLIをeditable導入する。

```sh
./scripts/mac/setup-copy-cli.sh --dry-run
./scripts/mac/setup-copy-cli.sh
```

導入にはHomebrewとPython 3.10以上が必要である。Homebrew自体の導入、SSH鍵の作成・Ubuntuへの登録は、自動化せず事前に行う。

### 3. Macの実行環境を検査する

```sh
./scripts/mac/verify-copy-cli.sh
```

この検査はPython、venv内の `photo-copy`、PATH上のrsyncとExifToolを確認する。

### 4. ローカルコピーを試験する

`--layout classify`（既定）は撮影日時を読み、組を判定して `YYYY/YYYY-MM/{camera,smartphone}/` 直下へ改名・分類する。実写真や既存のライブラリを使わず、一時ディレクトリへ小さな試験ファイルを作成して確認する。コピー元は変更・削除されず、保存先は撮影日時のメタデータを取得できたファイルだけで構成される。

`--year-month` は省略できる。省略した場合は組ごとの撮影年月へ自動分類され、1回の実行で複数月にまたがる入力も扱える。`--year-month` を明示すると、その年月と食い違う撮影日時のファイルを未処理にし、撮影日時が取得できないファイルだけを原名のままその年月へ配置する（日時不明分の再実行に使う）。

```sh
trial_root="$(mktemp -d)"
mkdir -p "$trial_root/source/DCIM"
cp /path/to/a-small-test-file.jpg "$trial_root/source/DCIM/"

.venv/bin/photo-copy copy \
  --source "$trial_root/source" \
  --destination-root "$trial_root/destination" \
  --device camera \
  --transport local \
  --dry-run \
  --log-dir "$trial_root/logs"
```

通常実行では `--dry-run` を外す。保存先は次の形式である。SDカードの `DCIM/` などの内部階層は持ち込まない。

```text
<保存先ルート>/2026/2026-09/camera/20260911-143052_<原名>
```

動画（MOV/MP4）の撮影日時はQuickTimeのUTC記録を変換して得るため、変換に使う `TZ` の値によって結果が変わりうる。既定は固定値 `Asia/Tokyo` であり、実行ホストの設定には依存しない。海外で撮影した動画をその場のタイムゾーンで配置したい場合だけ `--timezone <IANA名>` を明示する。

同名候補が既に配置先にある場合、サイズとSHA-256による内容一致を確認できたものだけ自動的にスキップする（`skipped`、終了コードに影響しない）。内容が異なる同名ファイルは上書きせず衝突として報告する。中断や部分失敗の後も同じコマンドを再実行してよい。前回の状態を記録するファイルは無く、保存先の実体だけで再実行の安全性が決まる。

経路c（`PhotoWork` からUbuntuの主HDDへの転送）に相当する、既存の相対配置を維持する場合は `--layout preserve` を使う。この場合 `--year-month` と `--device` は指定できず、ExifToolも呼ばない。コピー元からの相対パスが `YYYY/YYYY-MM/{camera,smartphone}/名前` のちょうど4階層でない場合や、シンボリックリンクの場合は未処理として報告する。

```sh
.venv/bin/photo-copy copy \
  --source "$trial_root/photowork" \
  --destination-root "$trial_root/destination" \
  --layout preserve \
  --transport local \
  --dry-run \
  --log-dir "$trial_root/logs"
```

`--only` を指定すると、`--source` からの相対パスの部分木だけを対象にできる（繰り返し指定可）。絶対パスや `..` を含む指定は実行不能（終了コード2）になる。`.DS_Store` や `._` で始まるファイルなど、OSが作る雑多ファイルは両モードで自動的に除外され、要約と詳細ログに件数が残る。

コマンドは要約を表示し、詳細を `--log-dir` のJSONファイルへ保存する。`--log-dir` を指定しない場合は、実行時のカレントディレクトリに `.photo-copy-logs/` を作成する。衝突、失敗、未処理がなければ終了コードは0であり、いずれかがあれば1である。引数や転送種別が不正、あるいはSSH接続先・主HDDの検査に失敗して実行できない場合は2である。

ARW/JPEG/XMPの組はARW、HEIC/MOVの組はHEICの撮影日時を全ファイルへ適用する。基準ファイルがない、または基準ファイルから日時を取得できない組はコピーせず、コピー元を保持したまま未処理としてログへ記録する。未対応形式や日時を取得できない単体ファイルも同様である。

### 5. rsync over SSHでUbuntuの主HDDへコピーする

`--transport rsync-ssh` は実装済みである。`--host-config` に `scripts/hosts/*.env`（[ubuntu.md](ubuntu.md) 参照）を指定する。接続だけを確認したい場合は `photo-copy check` を使う（転送を伴わない）。

```sh
.venv/bin/photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

このコマンドは接続ユーザー、主HDDのマウントとUUID、配置先ルートの書き込み可否、Mac側・リモート側のrsyncバージョンを検査する。いずれかに失敗すると、転送を一切行わずに終了コード2で停止する。

経路aの例（`--destination-root` を省略すると、ホスト設定の `ARCHIVE_LIBRARY_ROOT`（既定 `/mnt/camera_archive/photo-library`）が既定になる。`--year-month` も省略でき、撮影年月へ自動分類される）。

```sh
.venv/bin/photo-copy copy \
  --source /Volumes/<SDカード> \
  --device camera \
  --transport rsync-ssh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run
```

通常実行では `--dry-run` を外す。SSH接続はOpenSSHのControlMasterで多重化し、コピー元・配置先の組ごとにrsyncを1回呼ぶ。転送は `--times --itemize-changes --ignore-existing` を使い、コピー元削除・削除同期・インプレース書き込みは行わない。`--ignore-existing` によるスキップは内容一致とはみなさず、衝突として報告する。内容一致によるスキップ（`skipped`）はローカル転送と同じくサイズとSHA-256で判定し、コピー元のハッシュはMac側、配置先のハッシュはリモートで計算するため、ファイル本体をハッシュ比較のためだけに転送し直すことはない。

隔離した試験先で確認する場合は、`ARCHIVE_LIBRARY_ROOT` 配下に試験用のディレクトリを作り、そこを `--destination-root` に指定する。`ARCHIVE_MOUNT` 配下でも `ARCHIVE_LIBRARY_ROOT` の外（例: 直下の年フォルダ）は、rsync.pyの事前検査が配置先ルートとして拒否する。試験後は忘れずに削除する。

### 6. iPhoneから取り込む（イメージキャプチャ）

iPhoneはイメージキャプチャでMacへ取り込んだ後、`photo-copy` で分類する。取り込み先はPhotoWorkの中ではなく `~/Pictures/PhoneImportInbox/<機器名>/` とする（[decisions.md](../plans/0006_copy-cli-foundation/decisions.md) の「イメージキャプチャの取り込み先はPhotoWorkの外に置く」参照）。理由は、PhotoWorkはHDDと同じ年月・機器別の分類済み構成を保つ前提であり、イメージキャプチャが吐く未分類の生ファイルをそのまま置くとこの前提が崩れるためである。

1. Lightning（またはUSB-C）ケーブルでiPhoneをMacへ接続し、初回は「このコンピュータを信頼しますか？」を許可する。
2. 「イメージキャプチャ」を開き、左のデバイス一覧でiPhoneを選ぶ。
3. 「読み込み先:」（`Import To:`）を「その他...」（`Other...`）にし、`~/Pictures/PhoneImportInbox/iphone` を選ぶ（無ければ作成する）。
4. 取り込みたい項目を選択し、「読み込む」（`Download`）をクリックする。Live Photoは左上に渦巻きアイコンが付いた写真であり、HEICと対になるMOVが同じ番号で取り込まれる。

```sh
mkdir -p ~/Pictures/PhoneImportInbox/iphone
```

取り込み後、`~/Pictures/PhoneImportInbox/iphone/` の生ファイルをPhotoWorkへ分類する。

```sh
.venv/bin/photo-copy copy \
  --source ~/Pictures/PhoneImportInbox/iphone \
  --destination-root ~/Pictures/PhotoWork \
  --device smartphone \
  --transport local
```

Live Photoの組（同じ撮影の`.HEIC`と`.MOV`）は、`.heic` が基準ファイルとして選ばれ同一の日時プレフィックスになる。分類が終わったら `~/Pictures/PhoneImportInbox/iphone/` の中身を空にする（コピー元保持の原則はこの一時置き場には適用しない）。

### 7. 定型設定（プロファイル）を使う

コピー元、配置先ルート、転送方式、ホスト設定、機器種別など経路ごとに固定される値は、プロファイル設定ファイルへまとめられる。既定の場所は `~/.config/photo-copy/profiles.ini` である（`--profile-config` で変更可）。相対パスはプロファイル設定ファイルの位置ではなくカレントディレクトリを基準に解釈するため、リポジトリのルートから実行する。テンプレートは [`scripts/mac/profiles.ini.example`](../../scripts/mac/profiles.ini.example) を参照する。

```sh
cp scripts/mac/profiles.ini.example ~/.config/photo-copy/profiles.ini
chmod 600 ~/.config/photo-copy/profiles.ini
# 実際のパスとホスト設定に合わせて編集する
```

```sh
.venv/bin/photo-copy copy --profile sd-to-ubuntu --dry-run
.venv/bin/photo-copy copy --profile sd-to-ubuntu
```

`--year-month` と `--dry-run` はプロファイルに書けない（実行ごとに判断する値のため）。コマンドライン引数はプロファイルの値を上書きする。適用したプロファイル名と解決後の全項目は詳細ログへ記録される。

### 8. 日常の取り込みを行う

通常のSDカード取り込みは、リポジトリのルートから次の1コマンドだけを実行する。SDは `/Volumes/CameraSD` として接続されていることを前提とする。プロファイルは手順7で作成した `~/.config/photo-copy/profiles.ini` を使う。

```sh
.venv/bin/photo-copy copy --profile sd-to-ubuntu
```

実行後は表示された要約だけを見る。対象の写真・動画に `衝突`、`失敗`、`未処理` がなければ、主HDDへの取り込みは完了である。詳細ログは実行時のカレントディレクトリの `.photo-copy-logs/` に自動保存される。コピー元のSDカードはこの時点で消去しない。

`未処理` にSDカードの管理用XML・DBなどの未対応形式だけが含まれる場合は、写真・動画の取り込み結果に影響しないため記録だけしてよい。写真・動画が未処理、衝突、失敗になった場合は、対応する詳細ログを開き、原因を解消して同じコマンドを再実行する。既に内容一致を確認できたファイルはスキップされるため、再実行で既存ファイルを上書きしない。

dry-runは毎回不要である。初回のSDカード、プロファイルや保存先の変更後、または問題を調査するときだけ、次を先に実行する。

```sh
.venv/bin/photo-copy copy --profile sd-to-ubuntu --dry-run
```

iPhoneは手順6でイメージキャプチャから `PhoneImportInbox` へ取り込み、`iphone-to-photowork`、必要に応じて `photowork-to-ubuntu` のプロファイルを順に使う。SDをMacで選別・現像するときは `sd-to-mac`、その後 `photowork-to-ubuntu` を使う。

### 9. コピー元を削除できる状態を確認する

取り込み完了はコピー元を消去できる状態と同義ではない。SDカード、iPhone、PhotoWorkなどのコピー元を整理するのは、対象の取り込み分について次のすべてを確認した後とする。0009では削除しない。

1. `photo-copy` の要約と詳細ログで、対象の写真・動画に衝突・失敗・未処理がないことを確認する。SDカードの管理用XML・DBはこの確認対象外である。
2. 0010の全件検証で、主HDD上の対象ファイルに欠損がなく、内容一致が確認済みであることを確認する。
3. 0013の第2 HDDバックアップで、対象の主HDDデータと必要な設定・DBがバックアップ済みであることを確認する。
4. 写真のオフサイト保護も必要な場合は、Amazon Photos Desktopが対象分のアップロード完了を示していることを確認する。動画はAmazonの対象外であるため、この項目の代わりにならない。

0013の完了後に、上記の対象・確認日・0010と0013の結果を記録してから、コピー元を手動で削除またはSDカードを初期化する。Immichへの表示はこの確認の代わりにしない。

SMBマウントは取り込みに使わず、Amazon Photosと必要時の参照用とする。

### 10. SMB共有の自動マウントを設定する

Amazon Photos Desktopが起動時・再起動後も対象フォルダを見失わないよう、ログイン時にSMB共有（`/Volumes/CameraArchive`）を自動マウントするLaunchAgentを設定する。autofsのアイドルアンマウントは、Amazon Photos Desktopが対象を黙って見失うリスクがあるため採らない（[proposal.md](../proposal.md) 6章、0008で比較・検証）。

初回だけ、Finderで `smb://<SMB_SERVER>/CameraArchive`（`SMB_SERVER` は `scripts/hosts/*.env` の値）に接続し、「このネットワーク共有を検索するときにパスワードを記憶」を選んでキーチェーンへパスワードを保存しておく。

```sh
./scripts/mac/setup-smb-mount.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run

./scripts/mac/setup-smb-mount.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

`~/Library/LaunchAgents/com.photo-manager.mount-CameraArchive.plist` を作成・登録し、`RunAtLoad` でログイン時に `scripts/mac/mount-camera-archive.sh` を実行する。既にマウント済みなら何もしない冪等なスクリプトである。

```sh
./scripts/mac/verify-smb-mount.sh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env
```

この検査はマウント位置、読み書き可否、LaunchAgentの登録を確認する。

### 11. Amazon Photos Desktopを設定する

インストール、ログイン、バックアップ対象フォルダの指定は手動で行う（0008で実機確認済み）。

1. Amazon Photos Desktopをインストールし、Amazonアカウントでログインする。
2. バックアップ対象フォルダとして、SMB共有経由の `/Volumes/CameraArchive/photo-library` を1つだけ指定する。年フォルダ（`2026` 等）を個別に追加する必要はない。年が変わっても対象指定を変えない（[proposal.md](../proposal.md) 4.1・6章）。
3. 動画（MP4/MOV）を対象外にする個別の除外設定は無く、静止画（JPEG・HEIC・ARW・現像済みJPEG）だけが自動的にアップロードされることを0008で確認済みである。動画がアップロードされる場合は、アプリの設定変更やバージョンによる挙動変化の可能性があるため、対応を再検討する。
4. 週次のバックアップ確認では、アプリのメイン画面の状態表示を見る。「BACKUP COMPLETE」等の正常表示でない場合（特に「DISCONNECTED」）は、SMB再接続だけでは自動回復しないため、**アプリ自体を再起動する**（0008で確認した既知の挙動）。
