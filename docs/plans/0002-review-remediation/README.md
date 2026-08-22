# photo-manager 修正計画（レビュー指摘への対応）

- Status: Active
- Created: 2026-08-22
- Updated: 2026-08-22
- Exit criteria: M1〜M6の完了、全テスト通過、実機受け入れ完了

[`docs/specification/`](../../specification/) を仕様、[`docs/architecture.md`](../../architecture.md) を恒久設計とし、2026-08-22 のコードレビューで検出した差分を解消するための計画。既存の安全性（上書きしない・検証前に公開しない・失敗を成功と報告しない）を弱める変更は行わない。

## 0. 方針

1. 安全性の欠陥（F1）とデータの置き場所を誤る欠陥（F2）を最優先で直す
2. 性能の問題（F3）は「検証の回数」ではなく「同じ検証の重複」だけを削る。恒久仕様が求める検証はすべて残す
3. 復旧不能状態（F4）と事前チェック順序（F5）を直し、import仕様の「事前チェック失敗時はデータ、台帳、一時ファイルを変更しない」を成立させる
4. 各修正は「失敗する回帰テストを先に追加 → 修正 → 全テスト通過」の順で行う
5. 仕様解釈が動くもの（F2）は ADR に残し、README にも書く

## 1. 修正項目

### F1. SIGINT / SIGTERM が1ファイルの失敗として握り潰される（最優先）

**症状**

コピー中に Ctrl-C を押しても取り込みが止まらず、当該ファイルだけが失敗として記録され、残りのファイルの処理が続く。再現結果:

```
failed | received SIGINT
copied | None            ← 中断後も次のファイルがコピー・公開される
```

**原因**

`RunInterrupted` が `OperationalError` の派生（`src/photo_manager/runtime.py:32`）であるため、`transfer_file` の最終ハンドラ `except (OSError, OperationalError)`（`src/photo_manager/transfer.py:248`）に捕捉され、`TransferStatus.FAILED` に変換される。`importer.py:235-237` はそれを通常のファイル単位失敗として扱い、ループを継続する。`mirror.py:166,207,236` の `except (LedgerError, OperationalError)` も同様に中断を握り潰す。

**修正内容**

- `RunInterrupted` の基底を `OperationalError` から `PhotoManagerError` へ変更し、`exit_code = 1` を明示する。中断は「操作の失敗」ではなく「実行の打ち切り」であることを型で表現する
- 変更後、`transfer_file` / `importer` / `mirror` の `except` 節は中断を捕捉しなくなり、`cli.main` の `except PhotoManagerError` まで伝播して終了コード1で終わる。`cli.py:124` の `isinstance(exc, RunInterrupted)` 判定と `finally: resources.cleanup()` はそのまま機能する
- 中断時の `.part` は `RunResources` に登録済みのため `cleanup()` が削除する。ファイル記述子は既存の `with` / `finally` で閉じられる。追加の握り潰し防止として、`transfer.py` の `except (OSError, OperationalError)` の直前に `except RunInterrupted: raise`（部分ファイル削除後の再送出）を置くかを実装時に判断する。基底変更だけで足りるなら追加しない

**影響ファイル**: `src/photo_manager/runtime.py`（他は変更なしで解決する見込み）

**テスト**（`tests/test_transfer.py`, `tests/test_import.py`）

- コピー中に SIGINT 相当を発生させたとき、`transfer_file` が結果を返さず `RunInterrupted` を送出すること
- 同じ状況で `import_handler` が後続ファイルをコピーせず `RunInterrupted` を再送出すること、および `cli.main` がそれを終了コード1へ変換すること
- 中断後に `_photo-manager/tmp/` に `.part` が残らず、正式名の不完全ファイルが存在しないこと（architectureの中断時不変条件）
- ロックが解放されていること

**受け入れ条件**: SIGINT / SIGTERM でロックが解放され、作成中の一時ファイルが残らず、終了コード1で終了することが、実際の転送経路を通るテストで確認できる。

---

### F2. QuickTime `CreateDate` + `TimeZone` の解釈がオフセット分ずれている疑い

**症状**

サイドカーXMLが無い、または壊れている MP4 のフォールバック経路で、撮影日時が現地時刻より UTC オフセット分ずれる可能性がある。JST なら9時間早くなり、日付・月フォルダを誤る。

**原因**

`src/photo_manager/metadata.py:157`:

```python
capture = CaptureTime(create.replace(tzinfo=zone), "quicktime:CreateDate+TimeZone")
```

import仕様は「MP4 の `CreateDate` はUTC保存」と明記している。UTC の壁時計に `tzinfo` を貼り替えると、UTC 値をそのまま現地時刻として扱うことになる。正しくは UTC として解釈してからオフセットへ変換する必要がある。

**先に確定させること（実装前）**

実機の MP4 1本（サイドカーXMLがあるクリップ）で、exiftool の実出力と XML の正解値を突き合わせる。XML の `CreationDate` はタイムゾーン付きの正解なので、これを基準に解釈を決められる。

```sh
/opt/homebrew/bin/exiftool -json -CreateDate -TimeZone /Volumes/<card>/PRIVATE/M4ROOT/CLIP/C0001.MP4
/opt/homebrew/bin/exiftool -s -G1 -time:all -TimeZone /Volumes/<card>/PRIVATE/M4ROOT/CLIP/C0001.MP4
grep CreationDate /Volumes/<card>/PRIVATE/M4ROOT/CLIP/C0001M01.XML
```

- naive な `CreateDate` + オフセット = XML の値 → UTC 保存。`create.replace(tzinfo=timezone.utc).astimezone(zone)` に修正する
- naive な `CreateDate` = XML の値（オフセット加算不要）→ 現地時刻保存。現行実装が正しいので、コードは変えずに事実を記録する
- `CreateDate` 自体がオフセット付きの場合 → そのオフセットを破棄せず、XML および別タグの `TimeZone` との一致を確認して採用する。不一致なら推測せず mtime フォールバックまたはファイル単位失敗のどちらにするかを ADR で確定する
- `TimeZone` タグが出力されない場合 → 現行どおり mtime フォールバック。その事実もテストと文書に残す

**修正内容**

- 確定した解釈に合わせて `metadata.py` の該当行を修正（または現状維持）し、根拠コメントを付ける
- `docs/decisions/0004-quicktime-capture-time.md` を追加し、実測した exiftool 出力・XML 値・採用した変換式を記録する
- README の日時判定の説明に「XMLが最優先、XMLが無い場合の MP4 の解釈」を1段落で追記する

**影響ファイル**: `src/photo_manager/metadata.py`, `docs/decisions/0004-quicktime-capture-time.md`, `README.md`

**テスト**（`tests/test_metadata.py`）

- QuickTime 経路の**壁時計値**を assert する（現行テストは `utcoffset()` と `source` ラベルしか見ていない）
- 実機で確認した値をそのまま固定値テストにする。XML あり・XML 壊れ・XML なしの3ケースで、同一クリップの日時が一致すること
- naive `CreateDate` + `TimeZone`、オフセット付き `CreateDate`、両者の不一致、片方だけ、不正値をそれぞれテストし、ADR で定めた扱いを固定すること
- 月境界をまたぐ値（例: 月初 06:00 JST）で、生成される `YYYY/YYYY-MM/` が変わらないことを `tests/test_naming.py` で確認する

**受け入れ条件**: QuickTime `CreateDate` と `TimeZone` のexiftool出力形式ごとの解釈がテストとADRで固定される。

---

### F3. 同じ全件ハッシュの重複実行

**症状**

仕様が求める検証回数を超えて、同じデータを繰り返しハッシュしている箇所がある。4TB のミラー再実行や128GB満杯のカード取り込みで、実用時間が数倍になる。ただし、ミラー宛先の台帳公開前後の2回の検証はmirror仕様の手順7・8が別々に要求しているため、見かけ上同じでも削除しない。

**原因と修正内容**

#### F3-a. `importer._verify_records` の検証値の受け渡しと最終確認（`importer.py:94-116`）

コピー時に「読みながら計算した元ハッシュ」と「開き直して `F_NOCACHE` で再計算した先ハッシュ」の一致を確認済みであり、スキップ時も計画段階（`naming._same_content`）で元と先の両方をハッシュ済み。ただし、これらは計画時または正式化時の値であり、eject 直前の再確認と同じ意味ではない。`flock` は協調的ロックで、ツール外からの変更までは防げないため、単に最終ハッシュを削除してはならない。

- `naming.TransferPlan` に `verified_digest: Optional[str] = None` を追加し、`_same_content` が計算した宛先ハッシュを SKIP 計画に載せる
- `importer` は最終計画だけでなく、COPIED は `TransferResult.digest`、SKIP は `verified_digest` を保持する構造化結果を `final_results` として残し、台帳照合へ渡す
- `_verify_records` は「台帳レコードの存在」「宛先の実サイズとレコードのサイズ一致」「レコードの digest が、この実行で検証済みの digest と一致」をまず確認する
- eject 直前には宛先を再度ハッシュし、台帳 digest と一致することを確認する。元ファイルの再ハッシュは、コピー時または SKIP 判定時の digest と元ファイルのサイズ・mtime が変わっていないことを確認できる場合に限り省略する。変化があれば元も再ハッシュし、不一致なら失敗とする
- レコード、この実行の検証値、最終宛先ハッシュのいずれかが食い違う場合は従来どおり失敗とし、eject しない

これにより、通常時の元ファイル再ハッシュは除去しつつ、[`specification/import.md`](../../specification/import.md) の「全対象ファイルがコピーと検証に成功、または宛先の同一内容を確認済み」「必要な全ファイルについて有効なレコードがある」と、eject 直前の宛先確認を維持する。

#### F3-b. `mirror` の宛先二重検証（`mirror.py:233-235`）

`_verify_target_data()` を呼んだ直後に `_verify_target()` が同じ `_verify_target_data()` を再実行している。ただし、[`specification/integrity.md`](../../specification/integrity.md) のmirror手順8は台帳置換後に全管理対象を再検証することを明示しているため、現行の2回は仕様上それぞれ意味があり、削除対象にはしない。

- 手順7の「台帳公開前の宛先データ全件検証」と、手順8の「台帳公開後の宛先データ全件再検証」をどちらも残す
- `_verify_target()` は台帳スナップショット一致と手順8のデータ再検証を担うことが分かる名前・コメントへ整理するが、ハッシュ回数は減らさない
- 将来この2回を統合する場合は、先にmirror仕様と脅威モデルを改訂し、ADRで根拠を残す。この修正計画では行わない

#### F3-c. `mirror` のコピー元二重検証（`mirror.py:165` と `:206`）

mirror仕様は「1. パス・UUID・書込可否・容量の確認 → 2. ロック取得 → 3. コピー元台帳と全転送対象の検証」であり、ロック前の全件ハッシュは求めていない。

- 実行時（非 dry-run）は `_source_records()` の全件検証をロック取得後の1回だけにする
- ロック前はコピー元台帳の読み込みと構文検査を行い、暫定計画・宛先競合・`extras`・必要容量を読み取り専用で算出する。ここで得た結果は表示と早期失敗のための暫定値とし、実行根拠にはしない
- 両ボリュームのロック取得後、コピー元全件を検証して records を確定し、計画、宛先競合、`extras`、必要容量をすべて再計算する。容量チェックを含む全条件が成立してから、宛先データまたは台帳を変更する
- dry-run は従来どおり全件検証を行う。dry-run の目的が「コピー元が健全か」の事前確認であるため

#### F3-d. `ledger.append_record` の台帳全読み直し（`ledger.py:321`）

1件追記するたびに台帳全体を読んで全行検証している（O(n²)）。排他ロック保持中は他の書き手が存在しないため、`importer` が保持している `ledger` 辞書を信頼できる。

- `append_record` に `known: Optional[Dict[str, LedgerRecord]] = None` を追加し、渡された場合は再読込せず重複判定に使う
- `importer` は既に保持している辞書を渡し、追記成功後に辞書を更新する。`supplement_record` も同様に受け渡す
- 引数を渡さない既存の呼び出し（テスト等）の挙動は変えない

**影響ファイル**: `src/photo_manager/naming.py`, `src/photo_manager/importer.py`, `src/photo_manager/mirror.py`, `src/photo_manager/ledger.py`

**テスト**

- SKIP 計画と COPIED 結果が検証済み digest を保持し、通常時に元ファイルの最終再ハッシュを行わないこと。一方、eject 直前の宛先ハッシュは必ず実行されること
- 検証後に元ファイルのサイズまたはmtimeが変わった場合は元も再ハッシュし、不一致なら eject されないこと
- 台帳の digest が実ファイルと食い違う場合は、従来どおり `ledger_complete=False` になり eject されないこと
- ミラー成功時に手順7・8の宛先全件検証が各1回行われ、仕様上必要な回数を下回らず、不用意な追加ハッシュもないこと
- ロック前にコピー元の全件ハッシュが走らないこと（非 dry-run）と、dry-run では走ること
- ロック後に計画、宛先競合、`extras`、必要容量が再計算され、再計算完了前に宛先が変更されないこと
- `append_record(known=...)` が重複追記を防ぎ、渡さない場合の既存挙動が変わらないこと

**受け入れ条件**: import・eject・mirror仕様が求める検証はすべて残ったまま、仕様上意味のないコピー元の重複ハッシュと、台帳追記ごとの全台帳再読込が消えている。ミラー手順7・8の2回の宛先全件検証は仕様上必要なため維持する。

---

### F4. 管理用一時ファイルの残骸が mirror / 台帳修復を恒久的に阻害する

**症状**

`_photo-manager/checksums.tsv.mirror.part` または `checksums.tsv.repair.part` が残ると、以後の `photo-mirror` は最終段で必ず失敗し、台帳の末尾修復も必ず失敗する。自動・手動いずれの復旧手順も存在しない。

**原因**

`ledger.replace_ledger`（`ledger.py:245-249`）と `ledger._replace_records`（`ledger.py:196-200`）は既存の一時ファイルを検出すると拒否する。一方でこれらを掃除する経路が無い（`transfer.cleanup_stale_parts` の対象は `_photo-manager/tmp/` 配下かつ `\d{8}_\d{6}_....part` のみ）。書き込みループの `except` は `OSError` のみを見るため、中断や例外では一時ファイルが残る。

**修正内容**

- 両関数の書き込み処理を、ファイル記述子の close を保証する `try / finally` と、公開前だけ一時ファイルを削除する `try / except BaseException` で包む。`published = False` のように置換前後の状態を明示し、`os.replace` 呼び出し前の例外・中断だけで unlink する。`os.replace` を呼び出した後は成否を推測して削除しない（現行の安全方針を維持）
- 起動時の掃除経路を追加する。排他ロックを保持している呼び出し元（import の台帳修復、mirror の台帳置換）に限り、残存する管理用一時ファイルを削除してから処理を続行できるようにする。API は明示的な引数（例: `allow_stale_temporary: bool = False`）とし、既定では従来どおり拒否する。ロックを取らない `photo-verify` からは決して有効化しない
- README の「台帳・ログと障害時の確認」に、残骸ファイル名と手動削除手順を追記する

**影響ファイル**: `src/photo_manager/ledger.py`, `src/photo_manager/mirror.py`, `src/photo_manager/importer.py`, `README.md`

**テスト**（`tests/test_ledger.py`, `tests/test_mirror.py`）

- 書き込み中に例外・中断が起きた場合、一時ファイルが残らないこと
- 事前に残骸を置いた状態で、ロックを保持する呼び出し元が復旧できること
- 同じ残骸がある状態で `photo-verify` は台帳を一切変更しないこと
- `os.replace` 後に発生した失敗では一時ファイルを削除しないこと（既存の安全方針の回帰）

**受け入れ条件**: 中断・異常終了の後、再実行だけで mirror と台帳修復が復旧する。復旧できない残骸が生じる経路が無い、または手順が文書化されている。

---

### F5. hard link / 書込可否 / 容量の事前チェックが「変更後」に実行されている

**症状**

hard link 非対応または容量不足の宛先に対して、台帳の末尾修復と古い `.part` の削除を実行してから終了コード2で中止する。[`specification/import.md`](../../specification/import.md) の「事前チェックが失敗した場合はデータ、台帳、一時ファイルを変更しない」に反する。

**原因**

`importer.py:172-194` の順序が「ロック → 台帳修復 → `.part` 掃除 → `ensure_writable` → `ensure_hard_links` → 計画 → 容量確認」になっている。書込・hard link の確認だけをロック直後へ動かしても、ロックファイルの作成が先行し、容量不足時には既に修復・掃除が終わっているため不十分である。

**修正内容**

- ロック前に、台帳を `repair_tail=False` で読み取り専用検査し、discovery → metadata → naming の暫定計画を作成する。末尾破損が修復可能な形なら「ロック後に修復予定」として扱えるよう、変更を伴わない検査APIを追加する
- `ensure_writable` と `ensure_hard_links` を実行した後、暫定計画に基づいて `ensure_capacity` を行う。プローブは成功・失敗・中断の全経路で自分が作ったファイルと新規ディレクトリだけを確実に片付ける
- 上記の事前チェックがすべて成功した後に排他ロックを取得する。ロック取得自体が常設管理ファイルを作り得るため、事前チェックより前には行わない
- ロック後に台帳を再読込し、許容される末尾破損だけを修復する。その後 `.part` を掃除し、authoritative な計画を再作成して容量を再確認する
- ロック後の再確認に失敗した場合はデータコピーや台帳追記を行わず中止する。既に仕様で許可された台帳修復・ツール所有 `.part` の掃除・常設ロック以外の変更は行わない
- dry-run は書込・hard link プローブ、ロック、修復、掃除を行わず、読み取り専用の計画・容量確認だけを行う
- [`architecture.md`](../../architecture.md) の処理境界（読み取り専用事前チェック → ロック後再確認 → 実行）に合わせる

**影響ファイル**: `src/photo_manager/importer.py`, `src/photo_manager/ledger.py`, `src/photo_manager/volumes.py`

**テスト**（`tests/test_import.py`）

- `os.link` が失敗する宛先で `photo-import` を実行したとき、終了コード2で中止し、台帳、`.part`、管理ディレクトリが変更されていないこと
- 容量不足でも、台帳修復、`.part` 掃除、ロック作成より前に終了コード2で中止すること
- 書込・hard link プローブの各障害点と中断で、プローブファイルやプローブのためだけに作ったディレクトリが残らないこと
- 事前チェック後・ロック前に宛先状態が変わった場合、ロック後の再計画・容量再確認で検出し、データコピーと台帳追記を行わないこと

---

### F6. 軽微な修正

| # | 内容 | 対象 |
|---|---|---|
| a | `-v / --verbose` を実際にログレベルへ反映する（DEBUG 出力を持つか、少なくとも詳細行の出力を切り替える）。実装しない場合はヘルプと README から削る | `cli.py:39`, `logging_utils.py`, `README.md` |
| b | 死コード `_phase1_preflight` と、そのためだけの未使用インポートを削除 | `cli.py:59-88`, `cli.py:17-23` |
| c | F5 のロック前容量確認で不足した場合は `UsageError` のまま伝播させ、終了コード2にする。ロック後の再確認または実行中に状態が変わって容量不足となった場合は操作失敗の終了コード1とし、事前チェックの誤りと区別する | `importer.py:160-163,190-194` |
| d | `[mirror] subdir` を `[dest] subdir` から継承させる。併せて `_target_extras` の未使用引数 `subdir` を削除 | `config.py:47,91`, `mirror.py:123` |
| e | `photo-verify` が読み取り専用マウントでもロックを省略せず動くよう、既存の常設ロックファイルを `O_RDONLY` で開いて `LOCK_SH` を取得するフォールバックを追加する。ロックファイルが無い、または共有ロックを取得できない場合はCLI仕様どおり終了コード2で中止し、ロックなしでは決して検証を続行しない。挙動を README に書く | `locking.py:25-41`, `verify.py:200`, `README.md` |
| f | `os.link` 成功後の `part.unlink()` 失敗を FAILED ではなく警告付き COPIED として扱う（正式ファイルは公開済みで台帳追記も可能なため）。その場合も宛先ディレクトリの fsync を行い、`.part` は `RunResources` に登録したまま終了時 cleanup を再試行する。警告を `TransferResult` に構造化して import / mirror の warnings に加算する | `transfer.py:35-47,235-251`, `importer.py`, `mirror.py` |
| g | 未使用変数 `rejected_videos` を削除 | `discovery.py:114` |
| h | 未文書の設定エイリアス（`[destination]` / `path` / `uuid` / `[import]` / `eject_after_success`）を削除するか、README と `config.example.ini` に明記する。既定は削除（設定ミスを黙って通さない） | `config.py:84-108`, `README.md` |

各項目は独立している。少なくとも d・e・f・h のように挙動が変わるものはテストを追加する。まとめて1コミットに固定せず、安全性や挙動が変わる e・f は独立コミットにしてレビューと切り戻しを容易にする。

---

## 2. テストの追加（恒久仕様・architectureで要求済みだが未カバー）

F1〜F5 に付随するテストとは別に、以下を追加する。

1. **import の end-to-end テスト**: 現行の `tests/test_import.py` は `_build_plans` を mock しているため、discovery → metadata → naming → transfer → ledger を通した経路が一度も走っていない。`determine_capture_times` / `_build_plans` に exiftool runner を明示的に注入できる引数を追加し、デフォルト引数へ束縛済みの `subprocess.run` の monkey patch に依存しないようにする。その runner だけを差し替え、実ファイル（JPG/ARW/MP4/XML を模した小さなバイト列）で「初回取り込み / 全件再取り込み（全スキップ・台帳重複なし）/ 一部再取り込み」を検証する
2. **eject のテスト**: `diskutil eject` の引数が `ParentWholeDisk`（`disk8`）であって `DeviceIdentifier`（`disk8s1`）ではないこと、eject 直前にマウントポイントを再確認すること、eject 失敗時に終了コード1になること
3. **中断復旧テスト**: 正式化後・台帳追記前に中断した状態を作り、再実行で `supplement_record` が補完し、補完完了まで成功扱いにならないこと
4. **月境界テスト**: F2 で確定した解釈のもと、月初・月末の動画が正しい月フォルダへ入ること

## 3. 実施順とマイルストーン

| 段階 | 内容 | 完了条件 |
|---|---|---|
| M1 | F1（中断）+ そのテスト | Ctrl-C で取り込みが即座に止まり、`.part` が残らない |
| M2 | F2 の実機確認 → 修正 → ADR 0004 + README | 壁時計値を固定値で assert するテストが通る |
| M3 | F5（順序）+ F4（残骸）+ テスト | 事前チェック失敗時に何も変更されない／中断後に再実行だけで復旧する |
| M4 | F3（不要な重複ハッシュ・台帳再読込）+ テスト | 最終宛先検証とミラー手順7・8を維持したまま、不要なコピー元再ハッシュとO(n²)台帳読込が消える |
| M5 | F6（軽微）+ §2 のテスト追加 | 全テスト通過、README と実装の齟齬なし |
| M6 | 実機受け入れ（ルートREADMEの受け入れ確認を再実行） | テスト用SD・テスト用ボリュームで一連の確認が完了 |

M1・M3 は安全性、M2 はデータの正しさに関わるため、実機運用の再開前に必須。M4 は運用時間の問題であり、実機受け入れと並行して進めてよい。

## 4. 各段階での検証コマンド

```sh
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v   # 3.9.6（実機の既定）
PYTHONPATH=src python3 -m unittest discover -s tests               # pyenv 3.10.13
```

3.8 に無い API を使っていないことはレビューで担保する（`zoneinfo` / `str.removeprefix` / `dict` の `|` / `Path.is_relative_to` を使わない）。

## 5. この計画で変更しないこと

- SDカードへの書き込み・削除は引き続き一切実装しない
- `.part` からのアトミック正式化（`os.link` + `unlink`）と、`_photo-manager/tmp/` という配置（ADR 0003）は維持する
- 台帳形式（ADR 0002）は変更しない。F3-a・F3-d は読み書きの回数のみを変え、ファイル形式には触れない
- 宛先の既存ファイルを置換する経路は追加しない。F4 のアトミック置換は管理ファイルに限る
- eject の条件は緩めない。F3-a はこの実行で得た検証値を台帳照合へ受け渡して元ファイルの不要な再ハッシュを省くが、eject 直前の宛先再ハッシュは維持する
