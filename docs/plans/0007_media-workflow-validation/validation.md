# 0007 検証記録

## 2026-09-12: 段階1 正規の配置先を使える状態にする

- 主HDD `/mnt/camera_archive/2026/2026-08/` にあったCLI導入前の手動SMBコピー4件（`DSC00020.JPG`、`DSC00091.ARW`、`DSC00091.ARW.xmp`、`DSC00091_edit.jpg`）を削除した。対応するSDカード上の原本は既になかったが、`~/Pictures/backup/PhotoInbox/current/sony-08-25/DCIM/100MSDCF/` に4件とも存在することを確認したうえで削除した。あわせてmacOSが作った `._*` 4件と `.DS_Store`／`._.DS_Store` も削除した。
- `~/Pictures/backup/` はPhotoWorkの外にあり0007の配置先ではないため、保持・削除いずれの判断も0007の対象外とした（今回の作業では扱わない）。
- `photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env` が成功した（`OK: 接続先 ubuntu、配置先ルート /mnt/camera_archive、Mac側rsync rsync version 3.5.0 protocol version 32、リモートrsync rsync version 3.2.7 protocol version 31`）。

## 2026-09-12: 段階2 SDカードの代表メディアを正規の配置先へ置く

代表サンプルとしてSDカードの `DCIM/100MSDCF/DSC00305.{ARW,JPG}`（ARW+JPEGの組）、`DCIM/100MSDCF/DSC00241.JPG`（JPEG単独）、`PRIVATE/M4ROOT/CLIP/C0006.MP4`（動画）の4件を使った。

- Mac `~/Pictures/PhotoWork/` へ `--dry-run` → 本実行の順で配置した（`--device camera --layout classify`）。結果は「コピー済み4件、衝突・失敗・未処理・除外なし」。ログ: `.photo-copy-logs/copy-20260912-163908-721058.json`（dry-run）、`copy-20260912-163948-826258.json`（本実行）。
- 目視でMac側の配置結果（`PhotoWork/2026/2026-08/camera/`）を確認し、正しくコピーできていることを確認した。
- 主HDDへ `--transport rsync-ssh --host-config ./scripts/hosts/ubuntu-amane-yajima.env` で同じ4件を配置した。結果は同じく「コピー済み4件、衝突・失敗・未処理・除外なし」。ログ: `copy-20260912-164132-045041.json`（dry-run）、`copy-20260912-164240-282459.json`（本実行）。
- Macローカルおよび主HDD側（SMB `/Volumes/CameraArchive`）の両方で、目視で閲覧・再生できることを確認した。

## 2026-09-12: 段階3 iPhoneの代表メディアを正規の配置先へ置く

`~/Pictures/PhoneImportInbox/iphone/` に残っていた4件（`IMG_1525.HEIC`単独、`IMG_1526.MOV`単独、`IMG_1527.HEIC`+`IMG_1527.MOV`のLive Photoの組）を使った。

- Mac `~/Pictures/PhotoWork/` へ `--device smartphone --layout classify` で配置した。結果は「コピー済み4件、衝突・失敗・未処理・除外なし」。ログ: `copy-20260912-164450-948875.json`（dry-run）、`copy-20260912-164501-707968.json`（本実行）。目視で閲覧できた。
- 主HDDへ `--transport rsync-ssh` で同じ4件を配置した。結果は同じく「コピー済み4件、衝突・失敗・未処理・除外なし」。ログ: `copy-20260912-164549-736583.json`（dry-run）、`copy-20260912-164605-759330.json`（本実行）。SMB経由で目視で閲覧できた。
- 配置・確認後に `~/Pictures/PhoneImportInbox/iphone/` を空にした（手順6の運用どおりに戻せることを確認した）。

## 2026-09-12: 段階4 自動分類と例外の見え方

- SDカードの実データが2026-08と2026-09にまたがっていることを確認し、`DCIM/100MSDCF/DSC00306.ARW`（8月）と`DCIM/100MSDCF/DSC00456.ARW`（9月）を`--year-month`省略で同一実行に指定した。dry-runのログ（`copy-20260912-164907-428809.json`）で `DSC00306` → `PhotoWork/2026/2026-08/camera/`、`DSC00456` → `PhotoWork/2026/2026-09/camera/` に分かれる計画を確認し、本実行（`copy-20260912-164945-798397.json`）でも同じ結果になった。両ファイルとも目視で開けることを確認した。
- SDカードに実在する未対応形式ファイル `PRIVATE/DATABASE/DATABASE.BIN` を対象に実行し、要約が「未処理1件」、詳細ログ（`copy-20260912-165047-708398.json`）の該当項目が `status: "unresolved"`、`reason: "未対応の形式である"` として追跡できることを確認した。
- 撮影日時取得・基準ファイル判定・衝突・中断・再実行・日時不明の扱いは0006で実データ確認済みのため、0007では繰り返していない（[0006のvalidation.md](../0006_copy-cli-foundation/validation.md)参照）。

## 2026-09-12: 必要時の選別・現像確認

- 新構成でも不採用の組を削除できることを確認した。`PhotoWork/2026/2026-08/camera/`のRAW+JPEGの組（`DSC00305.ARW`/`.JPG`）と`PhotoWork/2026/2026-09/smartphone/`のLive Photoの組（`IMG_1527.HEIC`/`.MOV`）をゴミ箱へ移し、他のファイルが変更なく残っていることを確認した。SDカード・iPhone本体の原本には触れていない。
- darktableで `PhotoWork/2026/2026-08/camera/20260823-191612_DSC00306.ARW` を現像し、同じ`camera/`に`_edit`付きJPEG（7032×4688、sRGB。RAWの7040×4688とほぼ同一でフル解像度）を出力した。対応する`.xmp`もRAWの隣に生成された。
- 主HDD上の`20260823-191559_DSC00305.ARW`をSMB経由で直接darktableから現像した。遅延は問題に感じない程度で、`camera/`に`.xmp`と`_edit.jpg`が生成された。SMB書き込み時のmacOSメタデータ（`._*`）が3件付随したが、CLI経由の配置では発生しないものであり許容する。Macへのコピーは不要だった。
- 逆方向（Macで現像した結果を構成を保持したままHDDへ戻す操作）も確認した。0006では`--layout preserve --transport rsync-ssh`を隔離した試験先だけで確認していたため、正規の配置先どうしでの確認が抜けていた。Mac PhotoWorkにのみ存在した`20260823-191612_DSC00306.ARW`とその`.xmp`・`_edit.jpg`の3件を`--layout preserve --transport rsync-ssh`で`~/Pictures/PhotoWork`から`/mnt/camera_archive`へコピーし、dry-run・本実行とも`2026/2026-08/camera/`の相対パスを維持したまま3件が計画・配置され、SMB経由で開けることを確認した。ログ: `copy-20260912-170333-042065.json`（dry-run）、`copy-20260912-170400-753715.json`（本実行）。
- 既存XMPや現像済みJPEGの更新をHDDへ戻す明示的な更新手順・第2 HDDへの保存手順は0007の範囲外とし、0013で設計することとした。CLIは内容の異なる同名ファイルを衝突として報告し上書きしないため、通常の取り込みでの無断上書きは0006で確認済みである。
- 選別（M03、不採用の判断自体）は日常運用で選別が必要になったときに確認する。今回は削除対象を「不採用」として直接指定しており、選別作業自体の運用フローは未着手のまま保留する。

## 未確認事項・申し送り

- 選別（M03: 必要なときだけ選別できる、という運用フロー自体）は未着手のまま保留とした。日常運用で選別を使うときに確認する。
- `~/Pictures/backup/` の最終的な扱い（保持か削除か）は0007の対象外とした。判断が必要になった時点で改めて扱う。
- 0008（Amazon Photos）・0009（両経路の通し確認）・0013（更新手順の設計）へ渡す前提:
  - 正規の配置先（`~/Pictures/PhotoWork/`、`/mnt/camera_archive/`）には、現在の配置規則に従わないファイルは残っていない。
  - 段階2・3・4で配置した代表サンプル（SDカード4件＋複数月2件、iPhone4件）はテストコピーとして両ルートに残っている。0009の通し確認等で必要なければ削除してよい。
  - SMB（`/Volumes/CameraArchive`）経由での参照は問題なく機能する。
