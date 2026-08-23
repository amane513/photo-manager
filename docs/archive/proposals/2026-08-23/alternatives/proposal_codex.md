# 写真・動画管理環境 提案書

作成日: 2026-08-23  
対象: Sony α7C II、iPhone 13、MacBook Air、Ubuntu常時稼働PC

## 1. 結論

次の構成を推奨する。

- 4TB HDDをUbuntu PCへ常時接続し、選別済み写真・動画の「正本」とする。
- MacBook Airを取り込み、不要写真の削除、必要時のRAW現像を行う作業場所とする。
- MacからUbuntuへはSMBで、選別が完了した取り込み分だけを月別フォルダへ追加コピーする。
- ImmichはUbuntu上で動かし、HDD上の正本を読み取り専用のExternal Libraryとして参照する。
- ImmichからRAW（Sony ARW）を除外し、JPEG、HEIC、動画、現像済みJPEGだけを表示する。
- Amazon Photosには、Mac上で選別済みとなった写真だけをアップロードする。iPhoneの自動保存は使わない。
- 第2 HDDを追加し、原本、動画、現像データ、Immichデータベースを世代付きでバックアップする。
- 現像・選別はまず無料のdarktableを中心に始め、操作性や処理量に課題が出た時点でLightroom Classicを再検討する。
- 祖父母向け共有は当面「みてね」を継続する。ImmichまたはAmazon Photosへの移行評価は別プロジェクトとする。

この構成では、Immichを保管場所ではなく「正本を見やすくするための閲覧・検索システム」と位置づける。Immichの障害や将来の乗り換えがあっても、通常のフォルダとファイルとして写真を保持できることを重視する。

## 2. 確定した方針

| 項目 | 方針 |
|---|---|
| 主HDDの接続先 | Ubuntu PCへ常時接続 |
| 追加バックアップ | 第2 HDDを別途購入 |
| 初期の現像ソフト | 無料ツール。必要性が出たらLightroomを検討 |
| ImmichのRAW表示 | 表示しない |
| iPhoneの取り込み | Macで選別後、HDDとAmazon Photosへ送る。自動バックアップは使わない |
| 祖父母向け共有 | 今回は移行先を決めず、別途検討 |
| Ubuntu PC | Core i5、メモリ32GB、SSD 1TB、RTX 4060 Ti 16GB |

Ubuntu PCのメモリはImmichの公式推奨値を十分満たす。CPUの世代は不明だが、通常利用には概ね十分と見込む。RTX 4060 Tiは機械学習と動画変換の高速化に利用できるが、最初はCPU構成で正常動作を確認し、その後にGPUアクセラレーションを有効化する。

## 3. 全体構成

```text
Sony SDカード ─┐
                ├─> Mac: PhotoInbox
iPhone 13 ──────┘       │
                         ├─ 選別・不要データ削除
                         ├─ 必要なRAWだけ現像
                         ├─ Amazon Photosへ選別済み写真をバックアップ
                         │
                         └─ SMBで月別フォルダへ追加コピー
                                      │
                                      v
                         Ubuntu + 主HDD（正本）
                             │              │
                             │              └─> 第2 HDDへ世代付きバックアップ
                             │
                             └─> Immich External Library（read-only）
                                      └─ JPEG / HEIC / 動画 / 現像済みJPEGを表示
```

Amazon Photosは写真のオフサイトコピーとして有効だが、Primeの動画容量は5GBである。そのため動画の保護をAmazon Photosには依存しない。

## 4. 保存領域の役割

### 4.1 MacBook Air

Macは一時作業領域とし、恒久保管場所にはしない。

```text
~/Pictures/PhotoWork/
  PhotoInbox/
    current/             # 今回取り込んだ未選別データ
  ReadyForArchive/
    2026/
      2026-08/           # 選別済み。HDDとAmazon Photosへ送る
```

- `PhotoInbox` にSDカードとiPhoneから取り込む。
- 不要写真・動画を削除する。
- 必要なRAWだけ現像し、完成画像をJPEGで書き出す。
- 主HDDとAmazon Photosへの保存を確認するまで、作業データを消さない。
- 確認後、完了した作業コピーをMacから削除する。

内蔵SSDの空き容量は、少なくとも「1回の最大撮影量の2倍＋余裕」を維持する。

### 4.2 Ubuntuの1TB SSD

OS、Docker、Immich、PostgreSQL、サムネイル、機械学習データ、変換済み動画を置く。

例:

```text
/srv/immich/
  postgres/
  upload/
  model-cache/
```

PostgreSQLは公式要件に従い、ネットワーク共有や主HDDではなくローカルSSDに置く。Immichの派生データには、ライブラリ容量の10～20%程度が必要になる可能性がある。SSD使用量に警告を設定し、空き容量20%を目安に維持する。

### 4.3 Ubuntuの主HDD

選別済み原本の正本を置く。Ubuntuに直接接続するため、ファイルシステムはext4を第一候補とする。

月別フォルダを基本とし、旅行、七五三、運動会など、後からファイル単位でも探したい大きなイベントだけ専用フォルダへ分ける。

例:

```text
/srv/photo-library/
  2026/
    2026-08/
      a7c2/
        DSC00001.ARW
        DSC00001.JPG
        DSC00001.xmp
      iphone13/
        IMG_0001.HEIC
        IMG_0001.MOV
      edited/
        DSC00001_edit.jpg
      events/
        2026-08-10_summer-trip/
          a7c2/
          iphone13/
          edited/
```

原則としてカメラのファイル名は変更しない。同じ月の中で機器別フォルダに分ければ衝突を避けやすく、ARWとJPEG、Live PhotoのHEICとMOVの対応関係も保ちやすい。コピー時に同名ファイルが見つかった場合は上書きせず、撮影日時を付けて、対になるファイルを必ず同じベース名へ一括変更する。

Immichのメインタイムラインは、外部ライブラリのフォルダ名ではなく、写真・動画の撮影日時などのメタデータを使って表示する。そのため、日別・イベント別フォルダを作らなくても、時系列閲覧、人物検索、地図、検索には影響しない。フォルダ構成が効くのは、主にImmichの追加機能であるFolder viewと、Immichを使わずFinder等で直接探す場合である。月別を基本にして問題ない。

大きなイベントを専用フォルダにする利点は、ファイルとしてまとめて受け渡し・復元しやすいことにある。ただしExternal Libraryのフォルダが自動的にImmichのアルバムになるわけではない。Immich内でもイベントとしてまとめたい場合は、必要なものだけ手動でアルバムを作る。Immichへ一度取り込んだ後にファイルを別フォルダへ移すと、新しいアセットとして扱われ、Immich内のアルバムや説明等を失う可能性があるため、特別フォルダへ分ける判断は最初の保存確定前に行う。

月フォルダは `YYYY-MM`、特別イベントは `YYYY-MM-DD_event-name` とし、`/`、`:`など各サービスで問題になりやすい文字を避ける。

### 4.4 第2 HDD

主HDDと同容量では将来の増加や世代保持が難しいため、現在のデータ量と年間増加量を測定したうえで、可能なら6～8TB以上を推奨する。

第2 HDDは常時マウントせず、バックアップ時だけ接続して完了後に取り外す運用が望ましい。これにより誤削除、マルウェア、電源障害の同時被害を減らせる。単純なミラーは削除や破損も複製するため、履歴、暗号化、整合性検査、復元機能を備えるresticを初期推奨とする。将来クラウドへバックアップを追加する場合も、同じツールを継続利用しやすい。

## 5. 日常の取り込みワークフロー

### 5.1 カメラからの取り込み

1. SDカードからMacの `PhotoInbox/current/a7c2/` へ、ARWとJPEGを両方コピーする。
2. コピー完了後にファイル数を確認する。
3. darktableへ「参照として追加」し、JPEGを中心に選別する。
4. 不採用写真は、同じベース名のARWとJPEGを両方削除する。
5. 重要な写真だけARWを現像し、`edited/` にフル解像度、sRGB、JPEGで書き出す。
6. darktableのXMPサイドカーはARWと一緒に保存する。

最初の運用では、RAW+JPEG 10組程度を使い、評価、削除、XMP保存、JPEG書き出しが想定どおりになるか確認する。ツールによってRAWとJPEGのペア削除の扱いが異なるため、未確認の一括削除は行わない。

### 5.2 iPhoneからの取り込み

1. macOSの「イメージキャプチャ」でiPhoneから `PhotoInbox/current/iphone13/` へ取り込む。
2. Live PhotoはHEIC/JPEGとMOVの組であるため、同じベース名の2ファイルを維持する。
3. Finder、Quick Look、QuickTime Playerなどで写真と動画を選別する。
4. 不採用のLive Photoは静止画とMOVを両方削除する。
5. 主HDDと必要なクラウド保存を確認してから、iPhone側の原本を削除する。

Amazon PhotosとImmichのiPhone自動バックアップは、初期構成では無効にする。自動保存を有効にすると、Macで削除する前の不要写真までアップロードされ、今回の要件と合わない。

### 5.3 保存確定

選別後のファイルは、Macの `ReadyForArchive/YYYY/YYYY-MM/` 以下へ機器別にまとめる。大きなイベントだけ `events/YYYY-MM-DD_event-name/` へ入れる。次の順序を標準とする。

1. Mac上で選別と現像を完了する。
2. 選別済みの今回取り込み分を、Ubuntu主HDDの対応する月別フォルダへ追加コピーする。既存ファイルを削除する同期は行わない。
3. ファイル数、合計容量、代表ファイルの閲覧でコピーを確認する。可能ならチェックサム検証も行う。
4. Macの `ReadyForArchive` をAmazon Photos Desktopのバックアップ対象にし、今回追加した写真の完了を確認する。
5. Amazon Photos上でJPEG、HEIC、ARW、現像済みJPEGの代表ファイルを確認する。
6. 第2 HDDバックアップを実行する。
7. 3つの確認が終わってからSDカード、iPhone、Macの作業コピーを削除する。

Amazon Photos Desktopは双方向同期ではなくバックアップとして扱う。アップロード後のローカル削除とAmazon Photos上の削除は別操作である。

## 6. 無料ソフトでの選別・現像

### 初期推奨

- **darktable**: 写真の選別、評価、非破壊RAW現像、XMP保存に使用する。
- **Sony Imaging Edge Desktop**: Sony純正の色やRAW処理が必要な写真だけに使用する補助ツールとする。
- **macOS イメージキャプチャ**: iPhoneの原本を通常フォルダへ取り込む。
- **Finder / Quick Look / QuickTime Player**: 写真・動画の簡易確認に使用する。

darktableの現像内容はXMPに保存されるが、Immichがdarktableの現像結果を完全に再現するわけではない。家族に見せたい完成状態は、必ずJPEGへ書き出す。

### Lightroom Classicを再検討する条件

次のいずれかが継続的な負担になった場合に導入を検討する。

- RAW+JPEGのペア選別・削除に手間がかかる。
- 大量撮影時の比較、評価、検索が遅い。
- 人物、キーワード、イベントをMac側でも統合管理したい。
- カメラやレンズごとの現像品質・処理時間に不満がある。
- 複数イベントへの一括適用や書き出しプリセットが必要になった。

導入する場合はクラウド中心のLightroomではなく、ローカル原本を管理できるLightroom Classicを候補とする。カタログはMac内蔵SSD、原本はUbuntuの主HDDに置く。なおカタログのバックアップには写真原本が含まれないため、両方を別途保護する。

## 7. Immich構成

### 7.1 導入方針

- Ubuntu 64-bit、Docker Engine、Docker Compose pluginを使用する。
- `IMMICH_VERSION` はメジャーバージョンを固定する。
- PostgreSQLはSSDに置く。
- 主HDDのライブラリをコンテナへ読み取り専用でマウントする。
- 新規アップロード中心のUpload Libraryではなく、External Libraryを主に使用する。

マウント例の考え方:

```yaml
volumes:
  - /srv/photo-library:/external/photo-library:ro
```

Immichからファイルを削除・整理せず、ファイル操作はMacまたはUbuntuの正本側で行う。正本側で移動・改名したファイルは、Immichで別アセットとして再認識され、アルバムや説明などImmich内だけの情報を失う可能性がある。そのため、保存確定後のフォルダ移動と改名は原則行わない。

### 7.2 RAWを表示しない設定

External Libraryの除外パターンに、少なくとも次を設定する。

```text
**/*.ARW
**/*.arw
```

これによりARWは主HDDとAmazon Photosに保管しながら、ImmichにはJPEGだけを表示できる。導入時に小規模なテストライブラリで、大文字・小文字、XMP、編集済みJPEG、動画が期待どおり扱われることを確認する。

Immichには手動スタック機能があるものの、2026年8月時点でRAW+JPEGの自動スタックを必須前提にはできない。拡張子除外の方が単純で安定する。

### 7.3 スキャン

- Macから今回の取り込み分を完全にコピーした後にライブラリをスキャンする。
- コピー途中のフォルダを取り込ませない。
- 初期は手動または定期スキャンを使用する。
- Experimental扱いの自動監視には依存しない。

### 7.4 GPU利用

RTX 4060 Tiは、機械学習と動画トランスコードの高速化に利用できる。次の順序で導入する。

1. CPUのみでImmichの基本動作、検索、サムネイル生成を確認する。
2. NVIDIAドライバーとContainer Toolkitを整備する。
3. Immich公式手順に沿ってCUDA機械学習を有効化する。
4. 必要な場合のみNVENC/NVDECによる動画変換を有効化する。
5. 更新後は画像検索と動画再生をテストする。

GPU設定は必須ではない。初回導入時の問題切り分けを容易にするため、基本構成の安定後に追加する。

### 7.5 更新

- 本番稼働では`latest`へ無条件追従せず、メジャーバージョンを固定する。
- 更新前にリリースノート、破壊的変更、バックアップ完了を確認する。
- まずモバイルアプリ、その後サーバーを公式の互換方針に従って更新する。
- 大きな更新後はログイン、タイムライン、検索、動画再生、External Libraryのスキャンを確認する。

## 8. Amazon Photosの使い方

Amazon Prime会員は写真をフル解像度・容量無制限で保存できる。動画とその他のファイルは5GB枠を消費する。Sony ARWは対応形式に含まれるが、すべてのRAWを無条件に保証するものではないため、α7C IIで撮影したARWを少数アップロードし、表示とダウンロードを事前確認する。

### 推奨設定

- Mac版Amazon Photos Desktopを使用する。
- Macの `ReadyForArchive` だけをバックアップ対象にする。
- 写真のみを対象とし、動画は対象外にする。
- iPhoneのAuto-Saveは無効にする。
- 初回はJPEG、HEIC、ARW、現像済みJPEGを各数点アップロードし、原寸で再取得できることを確認する。
- Amazon Photos側でフォルダ整理や一括削除を行う前に、第2 HDDを確認する。

Amazon Photosに一括重複整理機能があることを前提にしない。アップロード元をMacの `ReadyForArchive` に一本化し、同じ写真をMacとiPhoneの両方からアップロードしない。

Prime解約や容量超過時にはアップロード・同期・共有が制限され、超過状態が続くとデータ削除の可能性がある。Prime継続状態を年1回確認し、Amazon Photosを唯一の保管先にはしない。

## 9. バックアップ設計

### 9.1 コピーの位置づけ

| データ | 主HDD | 第2 HDD | Amazon Photos | 状態 |
|---|---:|---:|---:|---|
| JPEG / HEIC | 正本 | バックアップ | オフサイト | 3コピーを確保 |
| ARW / XMP | 正本 | バックアップ | ARWのみオフサイト | XMPはローカル2コピー |
| 動画 | 正本 | バックアップ | 原則なし | オフサイト不在 |
| 現像済みJPEG | 正本 | バックアップ | オフサイト | 3コピーを確保 |
| Immich DB・設定 | SSD | 第2 HDD | なし | ローカル2コピー |
| Immichサムネイル等 | SSD | 必要に応じて | なし | 再生成可能なものあり |

重要な注意点として、第2 HDDを同じ家に保管する場合、動画は火災・盗難・災害に対するオフサイト保護を持たない。次のいずれかを将来追加することを推奨する。

- 第2 HDDを定期的に別の場所へ保管する。
- もう1台を用意して2台を交互にローテーションする。
- 動画だけBackblaze B2などの有料オブジェクトストレージへ暗号化バックアップする。

### 9.2 バックアップ対象

最低限、次を第2 HDDへ保存する。

- `/srv/photo-library` 全体
- ImmichのPostgreSQLバックアップ
- ImmichのUpload Libraryとプロフィール等
- Docker Composeファイルと`.env`（秘密情報としてアクセス制限する）
- darktableのXMPサイドカー
- 将来Lightroomを使う場合はカタログとカタログ設定

Immichの自動DBダンプが同じSSDまたは主HDD内にあるだけでは、機器故障に対するバックアップにならない。DBダンプを第2 HDDへコピーする。

### 9.3 頻度

- 新しいイベント取り込み直後: 主HDD、Amazon Photos、第2 HDDを確認する。
- 定期バックアップ: 週1回を基本とする。
- Immich DB: 日次ダンプを作成し、第2 HDD接続時にコピーする。
- バックアップ検証: 月1回の整合性チェック。
- 復元試験: 半年に1回、写真、動画、DBを一時領域へ復元する。

バックアップ中にImmichの整合性を確実にする場合は、短時間Immichを停止してDBとファイルを取得する。無停止で行う場合は、公式手順に従いDBを先に、ファイルシステムを後に取得する。

## 10. 祖父母向け共有

共有方法の移行判断は今回の導入範囲から外し、当面「みてね」を継続する。これにより、祖父母の操作変更と自宅サーバーの外部公開を、写真管理基盤の構築から分離できる。

Immichは初期段階では家庭内LANだけで使用し、ルーターからポート2283を直接公開しない。

別途比較する際は、次の小規模テストを行う。

| 候補 | 長所 | 主な確認点 |
|---|---|---|
| みてね継続 | 祖父母が操作に慣れている | 二重投稿の手間 |
| Amazon Photos Family Vault | Amazonアカウントで利用可能 | 対象選択、ダウンロード権限、動画容量 |
| Immich共有アルバム＋利用者アカウント | 写真・動画、時系列、検索を統合 | 外部アクセス、アプリ導入、保守 |
| Immich公開リンク | アカウント不要にできる | パスワード、期限、URL管理 |

Immichを家庭外から利用する場合は、祖父母端末を管理できるならTailscale等のVPNを優先する。通常のWebサービスに近い操作性が必要なら、独自ドメイン、HTTPS、リバースプロキシ、継続的な更新を含む運用設計が必要になる。

## 11. 導入手順

### Phase 0: 容量測定と小規模検証

1. 現在の写真・動画総容量を測る。
2. 直近1年分から年間増加量を見積もる。
3. 第2 HDDの容量を決める。
4. α7C IIのARW+JPEG、iPhoneのHEIC+Live Photo、動画を含むテストデータを用意する。
5. darktableで選別・現像・削除をテストする。
6. Amazon PhotosでARWのアップロードとダウンロードをテストする。

### Phase 1: 正本とバックアップ

1. 主HDDをext4で準備し、固定マウントする。
2. UbuntuにSMB共有を作る。
3. Macからテストイベントをコピーする。
4. 第2 HDDと世代付きバックアップを構成する。
5. 写真、動画、XMPを実際に復元する。

### Phase 2: Immich

1. SSD上へ公式Docker Compose構成で導入する。
2. 主HDDを`:ro`でマウントする。
3. テストフォルダをExternal Libraryへ登録する。
4. ARW除外、HEIC、Live Photo、動画、編集済みJPEGを確認する。
5. DBバックアップと復元を確認する。
6. 問題がなければ全ライブラリをスキャンする。
7. 必要に応じてGPUアクセラレーションを追加する。

### Phase 3: 日常運用への移行

1. Amazon Photos Desktopの対象を選別済みフォルダに限定する。
2. 1か月間、新旧フローを並行して確認する。
3. チェックリストを定着させる。
4. 容量、バックアップ結果、Immich更新を月1回確認する。

### Phase 4: 共有方法の比較

写真管理が安定してから、1イベントだけで「みてね」、Amazon Photos、Immichを比較する。祖父母本人の操作感を確認してから移行可否を判断する。

## 12. 日常運用チェックリスト

```text
[ ] SDカード/iPhoneからMacへ取り込んだ
[ ] ファイル数とLive Photoの組を確認した
[ ] 不要な写真・動画と対応するRAWを削除した
[ ] 必要なRAWを現像し、JPEGを書き出した
[ ] Ubuntu主HDDの月別フォルダへ今回分を追加コピーした
[ ] コピー結果を確認した
[ ] Amazon Photosで選別済み写真を確認した
[ ] 第2 HDDのバックアップを完了・検証した
[ ] Immichのスキャン後に表示を確認した
[ ] すべて確認後、Mac・SDカード・iPhoneの作業コピーを削除した
```

## 13. リスクと対策

| リスク | 対策 |
|---|---|
| 主HDDの故障 | 第2 HDD＋Amazon Photos。動画のオフサイト追加を検討 |
| 誤削除がバックアップへ反映 | 世代付きバックアップ、第2 HDDを通常時は取り外す |
| 選別前の写真がクラウドへ保存 | iPhone Auto-Saveを無効化し、Macの確定フォルダだけを対象化 |
| RAWとJPEGがImmichで二重表示 | ARWをExternal Libraryの除外パターンへ登録 |
| Immich障害で写真を見失う | 通常フォルダを正本にし、Immichはread-onlyで参照 |
| DBだけ復元してもアルバム等が戻らない | DBと関連ファイルを一組でバックアップし、復元試験を行う |
| SSD容量不足 | 派生データ10～20%を見込み、空き容量を監視 |
| 外部公開による侵入 | 初期はLAN限定。ポート2283を直接公開しない |
| Amazon Photosの重複 | アップロード元をMacの確定フォルダに一本化 |
| Prime解約・仕様変更 | Amazonを唯一の保管先にせず、年1回契約と復元性を確認 |

## 14. 未確定事項

実装開始前またはPhase 0で、次を確定する。

- 現在の写真・動画の総容量
- 年間の増加量
- 第2 HDDの容量と保管場所
- 動画のオフサイトバックアップを追加するか
- CPUの正確な型番とUbuntuのバージョン
- SMBを有線LANで利用できるか
- resticの世代保持期間、実行頻度、パスワードの保管方法
- 将来の共有方法と外部アクセス方式

これらのうち、現在容量と年間増加量は第2 HDDの購入判断に必須である。それ以外は段階導入中に決められる。

## 15. 参照資料

### Immich公式

- [Requirements](https://docs.immich.app/install/requirements/)
- [Docker Composeによるインストール](https://docs.immich.app/install/docker-compose/)
- [External Libraries](https://docs.immich.app/features/libraries/)
- [Folder View](https://docs.immich.app/features/folder-view/)
- [Supported Media Types](https://docs.immich.app/features/supported-formats/)
- [Backup and Restore](https://docs.immich.app/administration/backup-and-restore/)
- [Upgrading](https://docs.immich.app/install/upgrading/)
- [Hardware-Accelerated Machine Learning](https://docs.immich.app/features/ml-hardware-acceleration/)
- [Hardware Transcoding](https://docs.immich.app/features/hardware-transcoding/)
- [Remote Access](https://docs.immich.app/guides/remote-access/)
- [Sharing](https://docs.immich.app/features/sharing/)

### Amazon公式

- [Amazon Photos（日本）](https://www.amazon.co.jp/b?node=5262648051)
- [対応するファイル形式](https://digprjsurvey.amazon.co.uk/csad/help/node/GGU2SU8Y22DZYRMQ)
- [デスクトップアプリでのバックアップ](https://digprjsurvey.amazon.co.uk/csad/help/node/G5HFC9N4ETM8RLWJ)
- [iOSのAuto-Save](https://digprjsurvey.amazon.co.uk/csad/help/node/GTPNKDGX2ZJ3H43U)
- [Family Vault](https://digprjsurvey.amazon.co.uk/csad/help/node/GLSS4222BAQWWB3S)
- [容量超過時の扱い](https://digprjsurvey.amazon.co.uk/csad/help/node/G202146630)

### 現像・取り込み

- [darktable User Manual: Import](https://docs.darktable.org/usermanual/development/en/module-reference/utility-modules/lighttable/import/)
- [darktable User Manual: Sidecar Files](https://docs.darktable.org/usermanual/3.6/en/overview/sidecar-files/sidecar/)
- [Sony Imaging Edge Desktop](https://support.d-imaging.sony.co.jp/app/imagingedge/ja/)
- [Apple: イメージキャプチャユーザガイド](https://support.apple.com/guide/image-capture/welcome/mac)
- [Adobe: Lightroom Classicのファイル形式設定](https://helpx.adobe.com/uk/lightroom-classic/help/file-import-formats-settings.html)
- [Adobe: Lightroom ClassicカタログFAQ](https://helpx.adobe.com/lightroom-classic/kb/catalog-faq-lightroom.html)

### バックアップ

- [restic公式ドキュメント](https://restic.readthedocs.io/en/stable/010_introduction.html)
- [restic: リポジトリの検査](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)

## 16. 最終推奨

最初からすべてを自動化せず、次の最小構成から始める。

1. Macで選別する。
2. Ubuntuの主HDDへ保存する。
3. Amazon Photosへ選別済み写真だけを保存する。
4. 第2 HDDへ写真・動画・Immich DBをバックアップする。
5. Immichは主HDDをread-onlyで閲覧し、ARWを除外する。

この5点が安定してから、GPUアクセラレーション、バックアップ自動化、祖父母向け共有の順に追加する。特に優先すべき残課題は、現在容量の測定、第2 HDD容量の決定、動画のオフサイト保護である。
