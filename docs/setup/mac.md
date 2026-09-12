# Macの構築手順

SDカードとiPhoneからの取り込み、必要時の選別・現像、Amazon Photosへのバックアップを担当するホストの手順である。全体の流れは [README.md](README.md) を参照する。

## 前提

- UbuntuへSSH接続でき、Ubuntu側の主HDDとSMB共有が利用できる（[ubuntu.md](ubuntu.md)）。
- 作業フォルダは `~/Pictures/PhotoWork/` の1つとする。

## 手動で行う作業

- Amazon Photos Desktopのインストール後のログインと、バックアップ対象フォルダの指定。
- 現像ツールのライセンスやアカウントが必要な場合の初回設定。

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

```sh
trial_root="$(mktemp -d)"
mkdir -p "$trial_root/source/DCIM"
cp /path/to/a-small-test-file.jpg "$trial_root/source/DCIM/"

.venv/bin/photo-copy copy \
  --source "$trial_root/source" \
  --destination-root "$trial_root/destination" \
  --year-month 2026-09 \
  --device camera \
  --transport local \
  --dry-run \
  --log-dir "$trial_root/logs"
```

通常実行では `--dry-run` を外す。保存先は次の形式である。SDカードの `DCIM/` などの内部階層は持ち込まない。

```text
<保存先ルート>/2026/2026-09/camera/20260911-143052_<原名>
```

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

経路aの例（`--destination-root` を省略すると、ホスト設定の `ARCHIVE_MOUNT` が既定になる）。

```sh
.venv/bin/photo-copy copy \
  --source /Volumes/<SDカード> \
  --year-month 2026-09 \
  --device camera \
  --transport rsync-ssh \
  --host-config ./scripts/hosts/ubuntu-amane-yajima.env \
  --dry-run
```

通常実行では `--dry-run` を外す。SSH接続はOpenSSHのControlMasterで多重化し、コピー元・配置先の組ごとにrsyncを1回呼ぶ。転送は `--times --itemize-changes --ignore-existing` を使い、コピー元削除・削除同期・インプレース書き込みは行わない。`--ignore-existing` によるスキップは内容一致とはみなさず、衝突として報告する。

隔離した試験先で確認する場合は、`ARCHIVE_MOUNT` 配下に試験用のディレクトリを作り、そこを `--destination-root` に指定する。試験後は忘れずに削除する。

Amazon Photos Desktopの設定は0008で追加する。SMBマウントは取り込みに使わず、Amazon Photosと必要時の参照用とする。
