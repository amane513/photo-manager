# 0003: メディア操作ワークフロー検証

作成日: 2026-08-23  
状態: 進行中

## 目的

MacBook Air上で、写真・動画を安全に取り込み、選別し、必要時にRAWを現像して保存待ちの状態へ進められることを確認する。

次の対応関係を壊さずに扱えることを、実ファイルの小規模サンプルで検証する。

- Sony α7C IIのRAW（ARW）と撮って出しJPEG
- darktableのXMPサイドカー
- iPhoneのLive Photo（HEICとMOV）
- iPhoneの通常写真・動画
- RAWから書き出した現像済みJPEG

## 対象範囲

- Mac上の `~/Pictures/PhotoWork/PhotoInbox/current/` と `ReadyForArchive/` の作成
- SDカードおよびiPhoneからの原本取り込み方法の確認
- Finder、Quick Look、QuickTime Playerによる手作業の選別
- 対応するRAW/JPEG/XMP、Live PhotoのHEIC/MOVを組として扱う削除操作の確認
- darktableでのRAW現像、XMP作成、`camera/` へのJPEG書き出し
- 月フォルダまたはイベントフォルダへの分類と、元ファイル名を維持した移動
- 操作結果のファイル数、対応関係、再生・閲覧可否の記録

このプランはMac上の操作検証だけを対象とする。主HDDへの保存、Amazon Photosへのアップロード、Immichへの登録、iPhone・SDカード・Google Photosからの本データ削除は行わない。

## 実施状況

### 2026-08-25

- Sony SDカードのルート直下にあったフォルダを、`PhotoInbox/current/sony-sd-2026-08-25/` へコピーした。画像・動画ファイルだけを選別せず、`DCIM/` と `PRIVATE/` を含むカード内のフォルダ構成を維持した。
- `DCIM/` と `PRIVATE/`、ARW、JPEG、動画ファイルの存在を確認した。JPEGとARWはFinderのQuick Lookで、動画はQuickTime Playerで開けた。
- iPhoneからの画像・動画をMacへコピーした。HEICは8件、MOVは2件である。同名のHEIC/MOVは1組確認できた。もう1件のMOVに同名のHEICはなく、通常動画である可能性がある。HEICはFinderのQuick Lookで、MOVはQuickTime Playerで開けた。
- 削除操作の検証候補として、Sonyの `DSC00240.JPG` と `DSC00240.ARW`、iPhoneの `IMG_1380.HEIC` と `IMG_1380.MOV` を選んだ。まだ削除していない。
- 上記4ファイルをMac上のテストコピーからゴミ箱へ移した。各元フォルダに対応ファイルが残っておらず、ゴミ箱に4ファイルがあることを確認した。SDカードとiPhone上のコピー元には変更を加えていない。
- darktableを起動し、`DSC00241.ARW` を現像してJPEGを書き出せた。現像済みJPEGはRAWと同じフォルダに `DSC00241_edit.JPG` として出力した。`DSC00241.ARW.xmp` がRAWと同じフォルダにあることを確認した。出力JPEGは開け、ピクセル寸法は `4330 × 6494`、カラープロファイルはsRGBである。
- 今回のテストコピーは通常撮影として、`ReadyForArchive/2026/2026-08/` に分類することを決めた。

## 未実施・要確認事項

以下を完了し、`validation.md` に結果を記録するまで、このプランは完了としない。

- [ ] **M01のサンプル数を満たす。** SonyのRAW+JPEGを10組以上使い、RAWのみまたはJPEGのみのデータが存在する場合は各1件以上を含める。コピー前後の形式別ファイル数も記録する。
- [ ] **M02のサンプル数と取り込み方法を確認する。** macOSの「イメージキャプチャ」でiPhoneの原本を取り込み、Live Photoを10組以上、通常写真を数件、通常動画を1件以上使って確認する。現状で確認済みのLive Photoは1組のみである。
- [ ] **削除後の対応関係を確認する。** M04・M05で削除した組について、ARW/JPEG/XMPおよびHEIC/MOVの孤立ファイルがないことを確認し、削除した組と残った組を記録する。
- [ ] **M07の保存先で現像済みJPEGを書き出す。** `DSC00241_edit.JPG` は現在RAWと同じフォルダにあるため、採用RAWをフル解像度・sRGBで `ReadyForArchive/2026/2026-08/camera/` へ `_edit` 接尾辞付きで書き出し、FinderとQuick Lookで開けることを確認する。
- [ ] **M08を実施する。** 採用データを `ReadyForArchive/2026/2026-08/` の `camera/` と `smartphone/` へ実際に移動し、RAW/JPEG/XMP、Live Photo、現像済みJPEGの配置と対応関係を確認する。
- [ ] **M09を実施して結果を記録する。** 移動後の種別ごとのファイル数・容量・閲覧可否、未検証の形式または操作、問題点、0004・0006へ渡す操作ルールを `validation.md` に記録する。

## 前提と安全策

- テストは必ずSDカード・iPhone・Google Photos上の原本を削除せず、Macへコピーしたデータだけで行う。
- Sonyデータは、RAW+JPEGの組を少なくとも10組使用する。RAWのみまたはJPEGのみのデータがあれば、各1件以上も含める。
- iPhoneデータは、Live Photoを少なくとも10組、通常写真を数件、動画を1件以上使用する。実データが不足する形式は「未検証」と記録し、推測で合格にしない。
- 検証中は自動削除、一律リネーム、同期ツール、写真アプリからの書き出しを使わない。
- iPhoneの原本取り込みにはmacOSの「イメージキャプチャ」を使う。写真アプリからの書き出しは、本検証の取り込み方法に含めない。
- 各削除操作は、対象ファイルと対応ファイルを事前に一覧で確認してから、少数ずつ実行する。

## テスト用の構成

```text
~/Pictures/PhotoWork/
├── PhotoInbox/
│   └── current/                  # 今回取り込んだ未選別データだけを置く
└── ReadyForArchive/
    └── 2026/
        └── 2026-08/              # または YYYY-MM-DD_event-name/
            ├── camera/
            └── smartphone/
```

- 通常の撮影分は `YYYY-MM/`、旅行や行事などは `YYYY-MM-DD_event-name/` を使う。
- `camera/` と `smartphone/` は撮影機器の役割で分ける。機種名は使わない。
- 現像済みJPEGは、元RAW、XMP、撮って出しJPEGと同じ `camera/` へ `_edit` 接尾辞付きで出力する。
- 元ファイル名は維持する。同名衝突があった場合は上書きせず、衝突した組だけを同じベース名のまままとめて改名する。

## 検証項目

| ID | 操作 | 確認すること |
|---|---|---|
| M01 | SDカードから取り込む | ARWとJPEGのファイル数がコピー前後で一致し、Mac上で開ける。 |
| M02 | iPhoneから取り込む | HEIC、Live PhotoのHEIC+MOV、通常動画が原本としてコピーされ、Live Photoの組を確認できる。 |
| M03 | 選別する | JPEG・HEIC・動画をQuick Look等で確認し、不採用候補を選べる。 |
| M04 | RAW/JPEGを組で削除する | テストコピー上で不採用JPEGに対応するARWとXMPを特定し、採用組を残したまま少数組を削除できる。 |
| M05 | Live Photoを組で削除する | テストコピー上で不採用HEICに対応するMOVを特定し、少数組を両方削除できる。 |
| M06 | RAWを現像する | darktableでRAWを編集し、XMPをRAWの隣に保存できる。 |
| M07 | JPEGを書き出す | フル解像度・sRGB JPEGを `camera/` へ `_edit` 接尾辞付きで書き出し、FinderとQuick Lookで開ける。 |
| M08 | 保存先を分類する | 採用データを月またはイベント構成へ移動しても、各組と現像済みJPEGの位置を説明できる。 |
| M09 | 結果を確認する | 種別ごとのファイル数、削除した組、残った組、未検証の形式を記録できる。 |

## 実施手順

1. `PhotoWork` 配下にテスト用ディレクトリを作る。既存の作業データがある場合は、今回分と混在させない。
2. SDカードからRAW+JPEGを10組以上、iPhoneからLive Photo 10組以上、通常写真・動画を `PhotoInbox/current/` へコピーする。コピー元のファイル数を記録する。
3. Finderで拡張子・ベース名を確認し、ARW/JPEG、HEIC/MOVの対応表を作る。各形式をQuick LookまたはQuickTime Playerで開く。
4. JPEG、HEIC、動画を見て採用・不採用を決める。RAWはこの段階では選別対象にしない。
5. 不採用として選んだ少数のRAW+JPEG組とLive Photo組を、対応表と照合してテストコピーから削除する。削除後、孤立したARW、JPEG、XMP、HEIC、MOVがないか確認する。
6. 採用したRAWを少なくとも1件darktableで現像する。XMPがRAWの隣に作られることを確認し、フル解像度・sRGB JPEGを `camera/` へ `_edit` 接尾辞付きで書き出す。
7. 採用データを保存先の月またはイベントフォルダへ移す。必要に応じて `camera/` と `smartphone/` を作成する。
8. 移動後に、各形式を開く。ファイル数、容量、各対応関係、削除対象、現像済みJPEGの書き出し先を記録する。
9. `validation.md` に結果、問題、採否、次のプランへ渡す判断を記録する。テストコピーは、記録が完了してから削除してよい。

## 記録する結果

完了時に `validation.md` を追加し、次を記録する。

- 使用したサンプルの件数と形式ごとのファイル数
- SDカード・iPhoneからの取り込み方法、および原本として扱えたか
- RAW/JPEG、XMP、Live Photoの各対応関係を確認した方法
- 削除したテストコピーの組と、孤立ファイルの有無
- darktableのXMP保存とsRGB JPEG書き出しの結果
- 月・イベント・機器別フォルダ構成を使った結果
- 問題点、例外、日常運用へ反映する変更案
- 未検証の形式または操作と、その理由

## 完了条件

- RAW+JPEG、XMP、Live Photo、通常動画、現像済みJPEGを、少なくとも1件ずつMac上で確認できている。ただしサンプルが存在しない形式は未検証として記録されている。
- 不採用データを対応ファイルごとに削除する手順を、テストコピーで安全に実施できている。
- darktableのXMPサイドカーと、`camera/` の現像済みJPEGを確認できている。
- 採用データを月またはイベント、`camera` / `smartphone` の構成へ分類できている。
- 本データやコピー元を削除していない。
- 0004、0006で使う、確定または未解決の操作ルールが `validation.md` に記録されている。
