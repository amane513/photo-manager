# 0007: メディア操作ワークフロー検証

作成日: 2026-08-23

更新日: 2026-09-12

状態: 完了（2026-09-12にSDカードとiPhoneの代表メディアをPhotoWorkと主HDDの正規の配置先へCLIで配置し、Mac・SMB参照時の主HDDで開けること、複数月の自動分類、未対応形式の未処理報告、新構成での不採用ファイル削除、RAW現像（Mac・HDD双方）、Macで現像した結果を構成を保持したままHDDへ戻す操作を実機・実データで確認した。詳細は [validation.md](validation.md) を参照。選別の運用フロー自体（M03）は未使用のため保留のままとする）

## 目的

RAW+JPEG、Live Photo、通常動画をCLIでMacの `PhotoWork/` またはrsync over SSH経由の主HDDの正規の配置先へ置き、MacとSMB参照時の主HDDで開けることを確認する。選別・現像は通常の取り込みに必須とせず、使うときに必要な操作だけ確認する。

## 方針変更

[0004](../0004_simplify-photo-workflow/plan.md) により、Macは `PhotoWork/`、HDDは `/mnt/camera_archive/` の各1ルートとし、年月・機器別の構成に統一する。イベントフォルダと保存確定操作は廃止する。過去の実施記録は当時のパスのまま保持し、新構成での検証済みとは扱わない。

## 対象範囲と前提

- 0006のCLIで、Macの `~/Pictures/PhotoWork/` またはrsync over SSH経由の主HDD `/mnt/camera_archive/` へ少数のサンプルを配置する。両ルート以下は `YYYY/YYYY-MM/camera/` または `smartphone/` とする。配置後の主HDDを開く確認にはSMB（`/Volumes/CameraArchive`）を使ってよい。
- 0006の実機確認は、既存データへの実害を避けるため `/mnt/camera_archive/photo-copy-test-*/` の隔離した試験先だけを使い、確認後に削除した。0007は隔離した試験先ではなく正規の配置先へ置く最初のプランである。したがって既存ファイルとの関係（下記「現状」）を先に整理する。
- iPhoneの取得はイメージキャプチャを使い、`~/Pictures/PhoneImportInbox/<機器名>/`（PhotoWorkの外の一時置き場）へ取り込んでからCLIで分類する。手順とイメージキャプチャの実機画面表記は [docs/setup/mac.md](../../setup/mac.md) の「6. iPhoneから取り込む」に確立済みであり、0007ではこれをそのまま使う（新たに手順を決め直さない）。
- SD・iPhone・Google Photos等のコピー元は保持する。削除試験は今回のテストコピーだけで行う。
- 各形式1〜2組を目安に、形式・操作・例外を代表するサンプルを使う。一律10組の件数条件は設けない。未確認の形式は推測で合格にしない。
- 撮影日時の取得（タグ優先順位、基準ファイル、動画TZ、XMPの扱い）、同名スキップ・衝突・中断・再実行、`--only`、プロファイルは0006で代表メディアと実データを使って実機確認済みである（[0006のvalidation.md](../0006_copy-cli-foundation/validation.md) 参照）。0007ではこれを前提とし、同じ確認を重複して行わない。0007独自に確認するのは、正規の配置先へ配置した後にFinder・Quick Look・QuickTime Playerなどで開ける（閲覧・再生できる）ことと、SMB経由でも同じように開けることである。
- 両経路の通し確認は0009、Amazonは0008、Immichは0012で扱う。選別・現像項目の完了を後続の前提にしない。

## 現状（2026-09-12時点の実機確認）

0007に着手する前の実機の状態である。いずれも0007で配置先として使う場所にあり、先に扱いを決める必要がある。

- Mac `~/Pictures/PhotoWork/`: 2026-09-12に空にした。2026-08-25のテストコピー（旧構成の `DCIM/`、`PRIVATE/`、`PhotoInbox/current/{sony-08-25,iphone-08-25}`、`ReadyForArchive/`、1175件・約30GB）は `~/Pictures/backup/`（Picturesフォルダ直下、PhotoWorkの外）へ移動済みである。PhotoWorkは年月・機器別の分類済み構成だけを置く前提（[proposal.md](../../proposal.md) 4.1）を満たす状態になり、CLIでの配置を開始できる。
- Mac `~/Pictures/PhoneImportInbox/iphone/`: 0006で取り込んだ `IMG_1525.HEIC`、`IMG_1526.MOV`、`IMG_1527.HEIC`、`IMG_1527.MOV` の4件が残っている。分類後に空にする運用（[docs/setup/mac.md](../../setup/mac.md) 手順6）どおりにはまだ戻していない。
- 主HDD `/mnt/camera_archive/2026/2026-08/`: `DSC00020.JPG`、`DSC00091.ARW`、`DSC00091.ARW.xmp`、`DSC00091_edit.jpg` がある。いずれもCLI導入前にSMB経由で手動コピーしたもので、`camera/` の階層も日時プレフィックスも持たず、現在の配置規則に従っていない。あわせてmacOSがSMB書き込み時に作る `._DSC00020.JPG` などのリソースフォーク4件が同じ場所に、`.DS_Store` と `._.DS_Store` が `2026/` 直下に残っている（CLI経由の配置ではこれらは除外される）。
- SMBは `//amane-yajima@192.168.11.17/CameraArchive` を `/Volumes/CameraArchive` にマウント済みであり、参照確認に使える。

## 実施状況（変更前の履歴）

### 2026-08-25

- Sony SDカードのルート直下にあったフォルダを、`PhotoInbox/current/sony-sd-2026-08-25/` へコピーした。画像・動画ファイルだけを選別せず、`DCIM/` と `PRIVATE/` を含むカード内のフォルダ構成を維持した。
- `DCIM/` と `PRIVATE/`、ARW、JPEG、動画ファイルの存在を確認した。JPEGとARWはFinderのQuick Lookで、動画はQuickTime Playerで開けた。
- iPhoneからの画像・動画をMacへコピーした。HEICは8件、MOVは2件である。同名のHEIC/MOVは1組確認できた。もう1件のMOVに同名のHEICはなく、通常動画である可能性がある。HEICはFinderのQuick Lookで、MOVはQuickTime Playerで開けた。
- 削除操作の検証候補として、Sonyの `DSC00240.JPG` と `DSC00240.ARW`、iPhoneの `IMG_1380.HEIC` と `IMG_1380.MOV` を選んだ。まだ削除していない。
- 上記4ファイルをMac上のテストコピーからゴミ箱へ移した。各元フォルダに対応ファイルが残っておらず、ゴミ箱に4ファイルがあることを確認した。SDカードとiPhone上のコピー元には変更を加えていない。
- darktableを起動し、`DSC00241.ARW` を現像してJPEGを書き出せた。現像済みJPEGはRAWと同じフォルダに `DSC00241_edit.JPG` として出力した。`DSC00241.ARW.xmp` がRAWと同じフォルダにあることを確認した。出力JPEGは開け、ピクセル寸法は `4330 × 6494`、カラープロファイルはsRGBである。
- 今回のテストコピーは通常撮影として、`ReadyForArchive/2026/2026-08/` に分類することを決めた。

上記は旧構成（イベント・保存確定を前提としたフォルダ）での記録であり、新構成での検証済みとは扱わない。実体は2026-09-12に `~/Pictures/backup/` へ移し、PhotoWorkの外に置いた。

### 2026-09-12（0006で先行して確認した内容）

0006の実機確認で、0007の基本確認に必要な判断部分は先に済んでいる。0007では繰り返さない。

- SDカードの `DCIM/100MSDCF`（ARW+JPG、単独JPG）と `PRIVATE/M4ROOT/CLIP`（MP4）を実データで扱い、撮影日時・基準ファイル・年月の自動分類を確認した。`--only` による部分木指定も実機のSDカード構造で確認した。
- iPhone 13をイメージキャプチャで `~/Pictures/PhoneImportInbox/iphone/` へ取り込み、HEIC単独・MOV単独・Live Photo（HEIC+MOV）の代表例で基準ファイル判定を確認した。
- darktableで実際に生成した `DSC00805.ARW.xmp` を使い、ARW+XMPの組と単独XMPの扱いを確認した。
- これら代表メディアを `--transport rsync-ssh` で主HDD上の隔離した試験先へ実際に配置し、確認後に試験先を削除した。正規の配置先（`/mnt/camera_archive/2026/...`）へは配置していない。

## 基本確認の残作業

以下を `validation.md` に記録する。既存の結果とCLIのログを再利用し、全件の手書き転記は行わない。

### 段階1: 正規の配置先を使える状態にする

- [x] 2026-09-12: 旧構成のテストコピーを `~/Pictures/PhotoWork/backup/` から `~/Pictures/backup/` へ移し、PhotoWorkを空にした。コピー元（SDカード・iPhone）を保持しているため、この退避分は正本として扱わない。
- [x] 2026-09-12: `~/Pictures/backup/` はPhotoWorkの外にあり0007の配置先ではないため、今回の作業では扱わないと決めた（保持・削除いずれの判断も0007の対象外とする）。
- [x] 2026-09-12: 主HDD `/mnt/camera_archive/2026/2026-08/` の既存4件（手動SMBコピー由来）と、macOSが作った `._*`・`.DS_Store` を削除した。SDカード上には対応する原本は既になかったが、`~/Pictures/backup/PhotoInbox/current/sony-08-25/DCIM/100MSDCF/` に4件とも存在することを確認したうえで削除した。
- [x] 2026-09-12: `photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env` が成功した（`OK: 接続先 ubuntu、配置先ルート /mnt/camera_archive、Mac側rsync rsync version 3.5.0 protocol version 32、リモートrsync rsync version 3.2.7 protocol version 31`）。

### 段階2: SDカードの代表メディアを正規の配置先へ置く

- [x] 2026-09-12: CLIで `DCIM/100MSDCF` のARW+JPEGの組（`DSC00305`）・JPEG単独（`DSC00241`）と `PRIVATE/M4ROOT/CLIP` の動画（`C0006.MP4`）をMacの `PhotoWork/` と主HDD（rsync-ssh）へ配置した。4件ともコピー済み、衝突・失敗・未処理なし。
- [x] 2026-09-12: Mac側の配置結果を目視で確認し、正しくコピーできていることを確認した。
- [x] 2026-09-12: 主HDD側の配置結果をSMB（`/Volumes/CameraArchive`）から開き、Macローカル・SMBともに閲覧・再生できることを確認した。

### 段階3: iPhoneの代表メディアを正規の配置先へ置く

- [x] 2026-09-12: `~/Pictures/PhoneImportInbox/iphone/` に残っていた4件（HEIC単独・MOV単独・Live Photoの組）をCLIでPhotoWorkと主HDD（rsync-ssh）の両方へ配置し、いずれも目視で開けることを確認した。
- [x] 2026-09-12: 分類後に `~/Pictures/PhoneImportInbox/iphone/` を空にし、手順6の運用どおりに戻せることを確認した。

### 段階4: 自動分類と例外の見え方

- [x] 2026-09-12: 自動分類（`--year-month` 省略）でSDカード上の2026-08（`DSC00306.ARW`）と2026-09（`DSC00456.ARW`）の実データを同一実行で配置し、`PhotoWork/2026/2026-08/camera/`と`PhotoWork/2026/2026-09/camera/`にそれぞれ正しく分かれることを確認した。日時不明ファイルの扱いは0006で確認済みのため0007では繰り返さない。
- [x] 2026-09-12: SDカードに実在する未対応形式ファイル（`PRIVATE/DATABASE/DATABASE.BIN`）を対象に実行し、要約が「未処理 1件」、詳細ログの該当項目が `status: unresolved`・`reason: 未対応の形式である` として追跡できることを確認した。

### 段階5: 記録

- [x] 2026-09-12: 実行結果と代表形式の確認結果、未確認事項を [validation.md](validation.md) に記録した。
- [x] 2026-09-12: 0008・0009・0010へ渡す前提（正規の配置先の状態、残した未処理ファイル、SMB参照の可否）を [validation.md](validation.md) の「未確認事項・申し送り」に明記した。

## 必要時の選別・現像確認

日常運用で選別・現像を使うときに確認する。基本確認が済んだ後も、未使用の操作は保留としてよい。

- [x] 2026-09-12: 新構成でも不採用の組を削除できることを確認した。`PhotoWork/2026/2026-08/camera/`のRAW+JPEGの組（`DSC00305.ARW`/`.JPG`）と`PhotoWork/2026/2026-09/smartphone/`のLive Photoの組（`IMG_1527.HEIC`/`.MOV`）をゴミ箱へ移し、各フォルダに他のファイルが変更なく残っていることを確認した。SDカード・iPhone本体の原本には触れていない。
- [x] 2026-09-12: darktableで `PhotoWork/2026/2026-08/camera/20260823-191612_DSC00306.ARW` を現像し、同じ`camera/`に`20260823-191612_DSC00306_edit.jpg`（7032×4688、sRGB。RAWの7040×4688とほぼ同一でフル解像度）を出力した。`20260823-191612_DSC00306.ARW.xmp`もRAWの隣に生成された。
- [x] 2026-09-12: 主HDD上の `20260823-191559_DSC00305.ARW`（SMB経由）を直接darktableで現像した。遅延は問題に感じない程度で、`camera/`に`DSC00305.ARW.xmp`と`DSC00305_edit.jpg`が生成された。SMB書き込み時のmacOSメタデータ（`._*`）が3件付随したが、CLI経由の配置では発生しないものであり許容する。Macへのコピーは不要だった。
- [x] 2026-09-12: 逆方向（Macで現像した結果を構成を保持したままHDDへ戻す）も確認した。Mac PhotoWorkだけに存在した`20260823-191612_DSC00306.ARW`とその`.xmp`・`_edit.jpg`を`--layout preserve --transport rsync-ssh`で正規の配置先どうし（PhotoWork→`/mnt/camera_archive`）へコピーし、`2026/2026-08/camera/`の相対パスを維持したまま3件とも配置され、SMB経由で開けることを確認した。
- [x] 2026-09-12: 既存XMPや現像済みJPEGの更新をHDDへ戻す手順は0007の範囲外とし、対象を指定した明示的な更新手順と第2 HDDへの保存手順の設計を0010へ引き継ぐことを [validation.md](validation.md) に記録した。CLIは内容の異なる同名ファイルを衝突として報告し上書きしないため、通常の取り込みでは無断上書きが起きないことを確認済み（0006）。

## 検証項目

| ID | 区分 | 確認すること | 現況 |
|---|---|---|---|
| M01 | 基本 | SDの静止画・動画をCLIで取り込み、開ける | 2026-09-12に正規の配置先（PhotoWork・主HDD）で確認済み |
| M02 | 基本 | iPhoneのHEIC・Live Photo・通常動画を原本として取得・配置できる | 2026-09-12に正規の配置先（PhotoWork・主HDD）で確認済み |
| M03 | 任意 | 必要なときだけ選別できる | 未着手 |
| M04 | 任意 | 不採用のRAW/JPEG/XMPのテストコピーを削除できる | 2026-08-25の旧構成に加え、2026-09-12に新構成（`camera/`）でも確認済み |
| M05 | 任意 | Live PhotoのHEIC/MOVのテストコピーを削除できる | 2026-08-25の旧構成に加え、2026-09-12に新構成（`smartphone/`）でも確認済み |
| M06 | 任意 | 保存後もRAWを現像し、XMPを保存できる | 2026-09-12に新構成（`camera/`）で確認済み |
| M07 | 任意 | 現像済みJPEGをRAWと同じ `camera/` に追加できる | 2026-09-12に確認済み（フル解像度・sRGB） |
| M08 | 基本 | 年月・機器別の配置と、判定できないファイルの報告を確認できる | 2026-09-12に正規の配置先での複数月分類・未処理報告を確認済み |
| M09 | 基本 | ログと代表例の結果・未確認事項を残せる | 2026-09-12にvalidation.mdへ記録済み |
| M10 | 基本 | 正規の配置先にあったCLI導入前の手動コピーと旧構成のテストコピーを整理できる | 2026-09-12に完了。PhotoWork側は退避、主HDD側は原本の存在を確認したうえで削除した |
| M11 | 基本 | 主HDDの配置結果をSMB経由のMacから開ける | 2026-09-12に確認済み |

## 完了条件

- 基本確認の対象形式・配置・閲覧の結果を `validation.md` に記録している。未確認形式はその形式の運用判断を保留している。
- 正規の配置先（`~/Pictures/PhotoWork/` と `/mnt/camera_archive/`）に、現在の配置規則に従わないファイルを残していない。残す場合は理由と扱いを記録している。PhotoWorkの外へ退避した `~/Pictures/backup/` は、保持・削除のいずれであるかを記録していればよい。
- 任意の選別・現像は、確認済みまたは未使用のため保留と明記している。全任意項目の実施をプラン完了の条件にしない。
- コピー元・本データを削除していない。整理のために削除したものは、原本の所在を確認したうえで記録している。
- 0008・0009・0010へ渡す結果と未解決事項が明確である。
