# CLIと設定仕様

利用例と日常運用はルートの [`README.md`](../../README.md) を参照する。この文書はコマンドラインと設定ファイルの契約を定める。

## 設定ファイル

既定の設定ファイルは `~/.config/photo-manager/config.ini` である。Python標準ライブラリの `configparser` で読み、コメントを書けるINI形式を使用する。リポジトリの [`config.example.ini`](../../config.example.ini) を雛形とし、機器固有の実ファイルはGitへ追加しない。

```ini
[dest]
root = /Volumes/CameraArchive_M
volume_uuid = <primary volume UUID>
subdir = Camera

[source]
# 空欄なら安全な自動検出を使う
root =

[mirror]
root =
volume_uuid =
# 省略時は [dest] subdir を継承する
#subdir = Camera

[tools]
exiftool = /opt/homebrew/bin/exiftool

[options]
hash_algorithm = sha256
free_space_margin = 1.1
eject_after_import = true
```

設定名は雛形に記載されたものだけを受け付ける。旧名や別名を黙って解釈せず、不明な綴りは設定エラーとして報告する。

- `dest.root`, `dest.volume_uuid`: 主アーカイブ。常にUUIDを照合する。
- `dest.subdir`: 管理対象データの役割ディレクトリ。既定は `Camera`。
- `source.root`: 省略時は安全な自動検出を行う。
- `mirror.root`, `mirror.volume_uuid`: 2台目HDDを使用するときだけ設定する。
- `mirror.subdir`: 省略時は `dest.subdir` を継承する。
- `tools.exiftool`: 実行可能な絶対パス。
- `options.hash_algorithm`: 現在は `sha256` のみ。
- `options.free_space_margin`: コピー予定サイズへ掛ける空き容量の余裕率。
- `options.eject_after_import`: 全成功時にSDカードをejectするか。

## コマンド

```text
photo-import [--dry-run] [--source PATH]
             [--dest PATH --dest-volume-uuid UUID]
             [--no-eject] [--config PATH] [-v]

photo-verify [--month YYYY-MM | --year YYYY]
             [--dest PATH --dest-volume-uuid UUID]
             [--config PATH] [-v]

photo-mirror [--to PATH --to-volume-uuid UUID]
             [--dry-run] [--config PATH] [-v]
```

| コマンド | 動作 |
|---|---|
| `photo-import` | SDカードから主アーカイブへ取り込み、検証、台帳記録、条件付きejectを行う |
| `photo-verify` | 台帳と管理対象ファイルを照合する。常に読み取り専用である |
| `photo-mirror` | 検証済みの主アーカイブを2台目HDDへ非破壊同期する |

## オプションの規則

- `--config PATH` は既定以外の設定ファイルを指定する。
- `-v` / `--verbose` は詳細ログを有効にする。
- `--dest` と `--dest-volume-uuid` は必ず同時に指定する。片方だけなら使用方法エラーとする。
- `--to` と `--to-volume-uuid` も必ず同時に指定する。
- CLIでパスを上書きしてもUUID検証を省略しない。
- `--no-eject` は設定より優先して自動ejectを無効にする。
- `photo-import` と `photo-mirror` は `--dry-run` に対応する。
- `photo-verify` はもともと読み取り専用なので `--dry-run` を持たない。

dry-runと実行時は同じ計画作成ロジックを使う。実行開始時には事前チェック、台帳状態、衝突、容量を再評価するため、dry-run後に外部状態が変われば安全側に中止または再計画する。

## 終了コード

| コード | 意味 |
|---:|---|
| `0` | 対象がすべて完了した。非阻害警告を含む場合がある |
| `1` | 取り込み・検証・ミラーの失敗、未登録、データ不一致、実行中の障害 |
| `2` | 引数、設定、または状態変更前の安全な事前チェックの誤り |

dry-runでも、計画段階で取り込めない対象や競合が判明した場合は `1` とする。事前チェック後に外部状態が変わって実行中の検査に失敗した場合も、操作失敗として `1` とする。
