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

0006の現時点では、`local` 転送だけを実装している。実写真や既存のライブラリを使わず、一時ディレクトリへ小さな試験ファイルを作成して確認する。コピー元は変更・削除されず、保存先は撮影日時のメタデータを取得できたファイルだけで構成される。

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

コマンドは要約を表示し、詳細を `--log-dir` のJSONファイルへ保存する。`--log-dir` を指定しない場合は、実行時のカレントディレクトリに `.photo-copy-logs/` を作成する。衝突、失敗、未処理がなければ終了コードは0であり、いずれかがあれば1である。引数や転送種別が不正で実行できない場合は2である。

ARW/JPEG/XMPの組はARW、HEIC/MOVの組はHEICの撮影日時を全ファイルへ適用する。基準ファイルがない、または基準ファイルから日時を取得できない組はコピーせず、コピー元を保持したまま未処理としてログへ記録する。未対応形式や日時を取得できない単体ファイルも同様である。

`rsync-ssh` 転送は未実装であり、指定すると終了コード2で停止する。SSH接続先や実メディアを使う転送確認は、この転送層を実装してから隔離した試験先で行う。

Amazon Photos Desktopの設定は0008で追加する。SMBマウントは取り込みに使わず、Amazon Photosと必要時の参照用とする。
