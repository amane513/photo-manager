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

この検査はPython、venv内の `photo-copy`、PATH上のrsyncとExifToolを確認する。SSH接続先と実メディアを使う転送確認は、CLI実装後に0006の実機検証として行う。

Amazon Photos Desktopの設定は0008で追加する。SMBマウントは取り込みに使わず、Amazon Photosと必要時の参照用とする。
