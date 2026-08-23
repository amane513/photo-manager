# photo-manager

Sony カメラの SD カードから外付け HDD へ、検証しながら写真・RAW・動画を取り込む macOS 向けツールです。対象は `JPG`、`ARW`、`MP4` と動画に対応する `XML` だけです。保存先は `Camera/YYYY/YYYY-MM/` とし、既存データは上書きも削除もしません。

詳細な仕様、アーキテクチャ、設計判断、進行中の作業計画は [`docs/README.md`](docs/README.md) から参照できます。

## 最重要の安全事項

**このツールは SD カード内のデータを絶対に削除・上書き・リネームしません。** SD カードは読み取り元としてだけ扱います。成功時に行う `eject` は macOS から安全に取り外す操作であり、データ消去ではありません。

取り込み後も、ログ・件数・ハッシュを確認するまでは SD カードを保持してください。確認できたらカードをカメラへ戻し、必要なら**カメラ本体のフォーマット機能**でフォーマットします。Mac の Finder や本ツールから消去する運用はしません。

## 前提環境

- macOS、Python 3.8 以上（外部パッケージ不要）
- `exiftool`。絶対パスで設定します。Homebrew の標準例は `/opt/homebrew/bin/exiftool`
- 取り込み先・ミラー先は書き込み可能で、hard link を使える別ボリューム
- 取り込み先とミラー先の Volume UUID

`rsync` は使用しません。実行はリポジトリ直下から行えます。

## セットアップ

設定例をコピーして、HDD の実際のマウントポイントと UUID を設定します。UUID は `diskutil info -plist /Volumes/<volume>` などで確認してください。

```sh
mkdir -p ~/.config/photo-manager
cp config.example.ini ~/.config/photo-manager/config.ini
chmod 600 ~/.config/photo-manager/config.ini
```

`config.ini` の主な項目です。

- `[dest] root` / `volume_uuid`: 主アーカイブ HDD。UUID 照合に失敗した場合は中止します。
- `[dest] subdir`: 保存先の役割ディレクトリ（既定は `Camera`）。
- `[source] root`: SD カードのマウントポイント。空欄なら `/Volumes` から安全に自動検出します。候補が 0 件または複数件なら選ばず中止します。
- `[mirror]`: 2 台目 HDD の設定。導入するまで空欄のままにします。`[mirror] subdir` を省略すると `[dest] subdir` を引き継ぎます（両ボリュームは同じ構成を表すため）。
- `[tools] exiftool`: 実行可能な絶対パス。
- `[options] eject_after_import`: 全件成功・台帳確認済みの場合だけ eject するか（既定 `true`）。

設定ファイルは機器固有の情報を含むため Git に追加しません。

節名・項目名は `config.example.ini` に書かれているものだけを受け付けます。別名（`[destination]`、`path`、`uuid`、`[import]`、`eject_after_success` など）は用意していません。綴り違いを黙って無視して意図しない設定で走るより、未知の項目として中止するほうが安全なためです。

## 使い方

初回は重要でないテスト SD カードとテスト用ボリュームで必ず dry-run します。dry-run はコピー、台帳修復、一時ファイル掃除、eject を含む永続的変更を一切行いません。

すべてのコマンドで `-v` / `--verbose` を付けると、通常の進捗行に加えて DEBUG レベルの診断行がログとコンソールへ出ます。

```sh
# 取り込み計画だけを表示する（最初に必ず実行）
scripts/photo-import --dry-run

# SD カードを明示して実行する。--no-eject は確認中に便利
scripts/photo-import --source /Volumes/UNTITLED --no-eject

# 設定を変えずに主アーカイブを一時的に指定する場合（UUID は必須）
scripts/photo-import --dest /Volumes/CameraArchive_M \
  --dest-volume-uuid EEE32629-5947-39D0-8842-DEA8A879BDF2 --dry-run

# 全アーカイブ、年、月を検証する
scripts/photo-verify
scripts/photo-verify --year 2026
scripts/photo-verify --month 2026-08

# 2 台目 HDD へのミラー計画と実行
scripts/photo-mirror --dry-run
scripts/photo-mirror --to /Volumes/CameraArchive_Backup --to-volume-uuid '<mirror UUID>'
```

共通オプションは `--config PATH` と `-v` / `--verbose` です。`--help` で全オプションを確認できます。`photo-import` の `--source`、`--dest` と UUID、`photo-mirror` の `--to` と UUID は、片方だけ指定できません。

終了コードは `0` が完了、`1` がファイル検証不一致・不完全な取り込み・実行中の障害、`2` が引数・設定・安全な事前検査のエラーです。`photo-import --dry-run` でも計画に失敗対象があれば `1` です。

取り込みはコピー後に保存先を開き直して sha256 を再計算し、全対象に有効な台帳レコードがあるときだけ成功扱いにします。同名・同内容はスキップし、同名・別内容は `_2`、`_3` のような別名で保存します。既存ファイルを置き換える経路はありません。

### 撮影日時の判定

保存先の `YYYY/YYYY-MM/` と先頭の `YYYYMMDD_HHMMSS_` は撮影日時から決まります。静止画は EXIF `DateTimeOriginal`、動画は**サイドカー XML の `<CreationDate>`（タイムゾーン付き）が最優先**です。XML が無い、または壊れている動画は MP4 側のタグで判定します。このとき QuickTime の `CreateDate` は UTC で記録されているため、そのまま現地時刻として扱わず、`TimeZone` タグのオフセットへ変換してから使います（実測では `CreateDate` 11:22:20 + `TimeZone` `+09:00` が XML の `2026-08-18T20:22:20+09:00` と一致します。詳細は [ADR 0004](docs/decisions/0004-quicktime-capture-time.md)）。`CreateDate` 自体にオフセットが付いている場合はそれを尊重して同じ時点を保ちます。`CreateDate` と `TimeZone` の片方でも取得できない場合だけ、ファイル更新日時へフォールバックします。フォルダの年月は記録された現地時刻で決まり、UTC には正規化しません。

### eject と通常運用

設定で有効でも、dry-run でないこと、全対象のコピーまたは同一内容確認、全レコードの台帳確認、失敗 0 件のすべてを満たした場合だけ SD カードを eject します。条件を一つでも満たさない場合、カードは挿したままです。

成功メッセージを確認したら、カードをカメラに戻してカメラ内フォーマットを行う、という順序を推奨します。途中で中断した場合もカードは変更されず、再実行すると検証済み分をスキップして続きから処理します。

## 手動ハッシュ確認

必要に応じて、SD 上の元ファイルと HDD 上の対応ファイルを別途照合できます。

```sh
shasum -a 256 /Volumes/UNTITLED/DCIM/100MSDCF/DSC00001.JPG
shasum -a 256 /Volumes/CameraArchive_M/Camera/2026/2026-08/20260818_192925_DSC00001.JPG
```

出力先頭の 64 桁の値が一致することを確認します。`photo-verify` は `checksums.tsv` の全レコードと実ファイルを照合し、欠落、サイズ差、ビット腐敗、未登録ファイルを検出します。全件検証は容量に応じて長時間かかり、その間は import / mirror と同じアーカイブに対して実行できません。

## 台帳・ログと障害時の確認

- 実行ログ: `~/Library/Logs/photo-manager/import-YYYYMMDD-HHMMSS.log`（verify / mirror も同形式）。HDD 未接続時にも読めます。
- 台帳: `<HDD>/_photo-manager/checksums.tsv`。UTF-8・タブ区切り・LF の 6 列（相対パス、`sha256`、ハッシュ、サイズ、撮影日時、取り込み日時）です。
- 一時ファイルとロック: `<HDD>/_photo-manager/`。`Camera/` ツリーのデータファイルではありません。

失敗時は終了コードと該当ログを確認し、SD カードをフォーマットせずに同じコマンドを再実行してください。台帳の末尾だけが書きかけの場合は、元台帳をログディレクトリへ退避できる場合に限り修復します。途中の破損や不整合は自動修復せず停止します。

### 読み取り専用でマウントされた HDD の検証

`photo-verify` はロックなしでは決して検証を続けません。読み取り専用マウントでは常設ロックファイル `<HDD>/_photo-manager/import.lock` を新規作成できないため、既存のロックファイルを読み取り専用で開いて共有ロックを取得します。ロックファイルが存在しない、または共有ロックを取得できない場合は終了コード 2 で中止します。その場合は、一度書き込み可能な状態でいずれかのコマンドを実行してロックファイルを作成してください。

### 台帳の書きかけ一時ファイルが残った場合

中断や異常終了の直後に、次の管理用一時ファイルが残ることがあります。どちらも `_photo-manager/` 内の管理ファイルで、`Camera/` の写真・動画ではありません。

- `<HDD>/_photo-manager/checksums.tsv.mirror.part`（`photo-mirror` の台帳更新の書きかけ）
- `<HDD>/_photo-manager/checksums.tsv.repair.part`（`photo-import` の台帳末尾修復の書きかけ）

通常は再実行だけで復旧します。`photo-import`（台帳修復時）と `photo-mirror`（台帳更新時）は排他ロックを持っているため、残骸を削除してから処理を続け、ログに `Removed stale managed ledger temporary ...` を残します。`photo-verify` は台帳を一切変更しないので、残骸をそのままにします。

再実行しても `managed temporary already exists` で止まる場合は、他の photo-manager が動いていないことを確認したうえで、該当ファイルだけを手動で削除してから再実行してください。`checksums.tsv` 本体や `Camera/` 以下は削除しません。

```sh
ls -l /Volumes/CameraArchive_M/_photo-manager/
rm /Volumes/CameraArchive_M/_photo-manager/checksums.tsv.mirror.part
rm /Volumes/CameraArchive_M/_photo-manager/checksums.tsv.repair.part
```

## Amazon Photos

Amazon Photos のバックアップ対象には HDD の `Camera/`（必要なら `Phone/`）を指定し、ファイル種別フィルタは**写真のみ**にします。ARW は写真として扱われますが、動画はこの設定の対象外です。バックアップは一方向アップロードとして使います。

アップロード開始後にフォルダ構成や名前を変更すると、再アップロードや重複の原因になります。運用開始前にこの構成・命名規則を確定してください。`_photo-manager/` は対象にしません。

## 2 台目 HDD（ミラー）

主アーカイブを `photo-verify` で正常と確認してから、同じフォルダ構成で 2 台目 HDD を接続し、`[mirror]` を設定します。まず `photo-mirror --dry-run` でコピー件数・競合・容量を確認し、問題なければ実行します。

mirror は主アーカイブの台帳と全データを事前検証してからだけコピーします。宛先に同一内容があればスキップし、異なる内容の同名ファイルは**上書きしません**。宛先だけにあるファイルも削除しません。コピー後に宛先を検証してから台帳スナップショットを更新します。

## 受け入れ確認チェックリスト

通常運用へ移る前に、重要データを含まない媒体で次を確認します。

1. JPG、ARW、MP4、XML を含む少量データで `photo-import --dry-run` を実行する。
2. `--no-eject` 付きで取り込み、元と保存先を `shasum -a 256` でも照合する。
3. 同じ SD カードで再実行し、全件スキップ・台帳重複なしを確認する。
4. 同名別内容、壊れた XML、孤立 XML、コピー中断後の再実行を試す。
5. 保存先の 1 バイト変更、欠落、未登録ファイルを `photo-verify` が検出することを確認する。
6. 成功時の eject と、失敗時に eject されないことの両方を確認する。
7. テスト用 2 台目ボリュームで mirror と再 mirror を確認する。
8. 実 HDD では少量から開始し、ログ・台帳・Amazon Photos の対象設定を確認してから通常運用へ移る。

自動テストは次で実行できます。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## launchd テンプレート

[`scripts/com.example.photo-manager.plist`](scripts/com.example.photo-manager.plist) は意図的に無効状態で同梱されています。手動運用と上記の受け入れ確認が完了するまで有効化しないでください。自動起動では HDD 未接続時や意図しないタイミングに処理が始まる危険があるため、最初は手動実行を推奨します。

利用する場合は、コピーを `~/Library/LaunchAgents/` に置き、リポジトリ・設定・ログの絶対パスを自分の環境に合わせて変更します。特に `exiftool` は設定ファイルで絶対パスにしてください。`Disabled` を `false` にする前に、dry-run と手動実行が安定していることを確認してください。
