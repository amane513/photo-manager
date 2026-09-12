# 0008: Amazon Photosバックアップの確認と手順の正本化

作成日: 2026-09-12

更新日: 2026-09-12

状態: 着手中（段階1完了）

## 目的

主HDDの静止画がAmazon Photosへ継続してバックアップされる状態を確立する。日常は週次の進捗確認だけで済み、SMBの切断やMac再起動でバックアップが黙って止まらないことを確認する。年が変わってもバックアップ対象の指定を変えずに済むよう、主HDDのライブラリルートを1階層下げる。現在Macの手元だけにある設定を [docs/setup/mac.md](../../setup/mac.md) と [scripts/](../../../scripts/) へ反映し、新しいMacで同じ状態を組み直せるようにする。

## 現状（2026-09-12時点、着手前）

着手前の実機の状態である。ロードマップ作成時の想定（未設定から始める）とは異なり、バックアップ自体は既に動いている。

- Amazon Photos Desktopは導入・ログイン済みである。主HDDの `2026` フォルダ（SMB経由の `/Volumes/CameraArchive/2026`）をバックアップ対象に指定済みである。
- Amazon Photos Desktopは、SMBでマウントしたボリュームそのもの（`/Volumes/CameraArchive`）をバックアップ対象に指定できず、その1つ下の階層のフォルダしか指定できない。現在は年フォルダが直下にあるため、年が変わるたびに対象フォルダの追加が必要になる。
- ARWとJPGのアップロードに成功している。現時点で主HDDにある写真はすべてAmazonへ上がりきっていることを利用者が確認済みである。
- iPhoneのAmazon Photos Auto-Saveは既に無効である。
- Mac側のSMBマウントは永続化していない。[docs/setup/mac.md](../../setup/mac.md) にSMBマウントの手順はなく、[docs/setup/ubuntu.md](../../setup/ubuntu.md) の手順5でFinderから接続を確認しているだけである。Amazon Photos Desktopは対象フォルダが常に見えている前提で動くため、この状態は再構築性と再起動後の追従の両方で不足している。
- 主HDDとMacの `PhotoWork` には0007のテストコピー（SDカード由来6件、iPhone由来4件、および現像で生成したXMP・`_edit` 付きJPEG）が残っており、Amazon側へも上がっている（[0007のvalidation.md](../0007_media-workflow-validation/validation.md) 参照）。主HDD上の写真はこれがすべてであり、実運用規模の取り込みは0009から始める。
- 利用者は、主HDD上のテストコピーと、Amazon Photos側のデータを一度すべて削除してよいと判断した（2026-09-12）。主HDDのコピー元の原本はSDカード、iPhone本体、`~/Pictures/backup/` に残っている（[0007のvalidation.md](../0007_media-workflow-validation/validation.md) 参照）。

したがって0008は新規に設定するプランではなく、次の4つを行うプランとする。

1. Mac側のSMBマウントを永続化し、スクリプトと手順へ残す。
2. 主HDDのライブラリルートを1階層下げ、Amazonのバックアップ対象を年に依存しない1フォルダにする。
3. 既に動いている構成の挙動を、形式・例外・再起動について確認する。
4. Amazon Photos Desktop側の手動設定を `docs/setup/mac.md` へ正本として記載する。

## 対象範囲と前提

- 対象は主HDD `/mnt/camera_archive/` をSMBでマウントした `/Volumes/CameraArchive` である。Macの `~/Pictures/PhotoWork/` はAmazonのバックアップ対象にしない（[proposal.md](../../proposal.md) 6章）。
- ライブラリルートを `/mnt/camera_archive/` から `/mnt/camera_archive/photo-library/` へ移し、年フォルダはその下へ置く（Macからは `/Volumes/CameraArchive/photo-library/2026/...`）。Amazonのバックアップ対象は `photo-library` の1フォルダとする。
- 実データは移動しない。主HDD上のテストコピーを先に削除し、空のライブラリルートを作ってから代表メディアを置き直す。これによりパス変更に伴う重複アップロードの確認が不要になる。
- 名前は `photo-library` とする。[proposal.md](../../proposal.md) の構成図の「主HDD: photo-library」およびImmichのマウント先 `/external/photo-library` と用語を揃える。
- SMBの共有名・共有パス（`CameraArchive` = `/mnt/camera_archive`）とマウント位置 `/Volumes/CameraArchive` は変更しない。Macの `~/Pictures/PhotoWork/` にはこの階層を追加しない。PhotoWorkは相対配置 `YYYY/YYYY-MM/{camera,smartphone}/` を保つ。
- 保存対象はJPEG、HEIC、ARW、現像済みJPEGとし、動画（MP4/MOV）は対象外とする。XMPも対象外でよい。
- 確認は各形式1〜2件を目安とする。全件の目視や一律の件数条件は設けない。
- Amazon Photos Desktopのログイン、対象フォルダの指定、設定画面の操作は自動化できない。手動手順として `docs/setup/mac.md` に記載する。
- HDDで削除した写真がAmazonに残ることは許容する。両者の完全一致や削除の伝播は目指さない。
- 0007のテストコピーは段階2のローカル削除確認（A08）の対象として使い、主HDDと `PhotoWork` の両方から削除する。0009はテストコピーが残っていない状態から始める。
- Amazon側は全削除してよい（利用者判断）。旧Macフォルダや過去のiPhone Auto-Save由来のデータもここで消える。ローカルに原本がないものはこの時点で失われるため、削除は不可逆であり、削除前に内容と件数を記録してから実行する。
- 全削除により、以降は「Amazonに存在する＝新しいライブラリルートから上がった」と一意に判定できる。段階4以降の確認はこれを前提とする。

## 範囲外

- 主HDD全件のアップロード完了を待つこと。現時点で上がりきっていることは利用者が確認済みであり、以後は週次の進捗確認で扱う（[proposal.md](../../proposal.md) 6章の「取り込みごとの完了待ちはしない」）。
- 第2 HDDへのバックアップ（0010）、Immich（0011・0012）、全件の内容検証（0013）。
- iPhoneのAmazon Photosアプリ側の設定変更。Auto-Saveは既に無効であり、0008では無効であることの確認記録だけを残す。

## 実施手順

結果は `validation.md` に記録する。Amazon Photos Desktopの画面表記は実機のものをそのまま残す。

### 段階1: Mac側のSMBマウントを永続化する

- [x] 現在のマウント状態と認証情報の保存先（キーチェーン）を確認し、再起動後に何が失われるかを記録する。
- [x] 永続化の方式を決める。ログイン項目による自動接続とautofs（`/etc/auto_smb`）を比較し、Amazon Photos Desktopが起動時に対象フォルダを見失わない方を選ぶ。マウント位置が `/Volumes/CameraArchive` から変わる方式を採る場合は、Amazon側の対象指定への影響を先に確認する。
- [x] 決めた方式を冪等・dry-run付きのスクリプト（`scripts/mac/setup-smb-mount.sh` を想定）として実装し、実機で実行する。パスワードはコミットせず実行時に入力する。共有名・サーバー・利用者は `scripts/hosts/*.env` の既存の値を使う。
- [x] 確認用スクリプト（`scripts/mac/verify-smb-mount.sh` を想定）で、マウント位置、読み書き可否、未マウント時に誤って書き込まないことを判定できるようにする。

### 段階2: テストコピーを削除し、主HDDを空にする

0007のテストコピーを消す。削除の挙動確認（A08）を兼ね、以降の作業から実データの移動をなくす。

- [ ] 削除前に、主HDD `/mnt/camera_archive/` 配下の全ファイルの一覧（パス・サイズ）を取得し、`validation.md` へ残す。コピー元（SDカード、iPhone本体、`~/Pictures/backup/`）に原本があることを、削除するファイルごとに確認する。
- [ ] 数件を先に主HDDから削除し、Amazon側に残ることを確認する（A08）。残ることは許容する前提であり、削除の伝播は求めない。この確認はAmazon側の削除より前に行う。
- [ ] 残りも主HDDから削除し、`/mnt/camera_archive/` 直下を空にする（`lost+found` など、写真以外で残すものは記録して残す）。macOSが作った `._*` や `.DS_Store` も削除する。
- [ ] Macの `~/Pictures/PhotoWork/` からも同じテストコピーを削除する。0009はどちらにもテストコピーが残っていない状態から始める。
- [ ] Amazon側を全削除する（利用者判断）。削除は不可逆であり、旧Macフォルダや過去のiPhone Auto-Save由来のデータも消えるため、削除前にアプリ上の件数と、ローカルに原本がないと思われるものの有無を確認して `validation.md` へ記録する。ゴミ箱（削除済み）に残る期間と、そこからの復元可否も記録する。
- [ ] 削除後、Amazon側が空であることを確認する。以降は「Amazonに存在する＝新しいライブラリルートから上がった」と判定してよい。

### 段階3: ライブラリルートを新設し、CLIとスクリプトを追従させる

`/mnt/camera_archive/photo-library/` を正本のライブラリルートにする。段階2で主HDDが空であるため、実データの移動は発生しない。

- [ ] Ubuntu側で `/mnt/camera_archive/photo-library/` を写真保存用アカウントの所有（`ARCHIVE_OWNER:ARCHIVE_GROUP`、0755）で作成する。dry-runを備えた冪等なスクリプト（`scripts/ubuntu/setup-library-root.sh` を想定。`setup-primary-storage.sh` へ組み込む案も検討してよい）として実装し、2回実行しても同じ結果になることを確認する。
- [ ] ホスト設定に `ARCHIVE_LIBRARY_ROOT`（例: `/mnt/camera_archive/photo-library`）を追加する。`scripts/hosts/ubuntu-amane-yajima.env` と `scripts/hosts/ubuntu.env.example` の両方を更新する。
- [ ] CLIを追従させる。[src/photo_copy/hosts.py](../../../src/photo_copy/hosts.py) の必須項目へ追加し、読み込み時に `ARCHIVE_MOUNT` 配下であることを検証する。`--destination-root` 省略時の既定を `ARCHIVE_MOUNT` からライブラリルートへ変更し（[src/photo_copy/cli.py:181](../../../src/photo_copy/cli.py#L181)、[src/photo_copy/cli.py:237](../../../src/photo_copy/cli.py#L237)）、[src/photo_copy/rsync.py](../../../src/photo_copy/rsync.py) の事前検査は「マウント済みであること」と「配置先ルートがライブラリルート配下であること」を判定するようにする。
- [ ] `tests/` を更新し、`.venv/bin/python -m unittest discover -s tests` が通ることを確認する。テストは一時ディレクトリだけを使い、実機の接続先に依存させない。
- [ ] `scripts/ubuntu/verify-primary-storage.sh` にライブラリルートの存在・所有者・権限の判定を追加する。`scripts/ubuntu/verify-unmounted-primary-storage.sh` では、未マウント時にライブラリルートが存在しないことを判定する（Amazon側で対象フォルダが消えることを、未マウントの検知に使う）。
- [ ] Macから `/Volumes/CameraArchive/photo-library/` が見えること、`photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env` が新しい既定の配置先で成功することを確認する（A12）。
- [ ] Amazon Photos Desktopのバックアップ対象を `2026` から `photo-library` へ差し替える。差し替え時点で中身は空でよい。画面表記は実機のものを `validation.md` へ残す。

### 段階4: 代表メディアを置き直し、形式ごとのアップロードと再取得を確認する

- [ ] SDカードとiPhoneから代表メディア（JPEG、HEIC、ARW、動画、Live Photoの組）を `photo-copy` で主HDDへ配置する。`--destination-root` を省略し、新しい既定がライブラリルート配下になることを確認する（A12）。配置先が `photo-library/2026/2026-MM/{camera,smartphone}/` になることを確認する。
- [ ] 現像済みJPEGとXMPは、配置したARWをdarktableで1件現像して作る（0007と同じ手順）。
- [ ] 各形式がAmazon側に現れることを確認する（A01）。年フォルダを対象へ追加する操作をしていないこと（`photo-library` の指定だけで済んでいること）を明記する。
- [ ] 各形式1件をAmazonからダウンロードし、開けること、元ファイルとサイズ・SHA-256が一致することを確認する（A02）。一致しない形式がある場合は、その形式の扱いを保留として記録する。
- [ ] HEICの表示・再取得がJPEGと同等に扱えるかを確認する。差異がある場合は記録し、運用上の影響を判断する。
- [ ] 同じコマンドを再実行し、内容一致による同一スキップが従来どおり動くことを確認する（A12）。

### 段階5: 動画除外と対象範囲を確認する

- [ ] 主HDDにあるMP4・MOVがAmazon側に上がっていないことを確認する（A03）。動画は年月・機器別フォルダの中に静止画と混在しており、対象フォルダの指定では分離できない。除外はアプリ側の設定に依存する。
- [ ] 動画が上がっている場合は、アプリ側に除外設定があるかを確認する。無い場合は、動画がAmazonへ上がることを許容するか、動画を別のライブラリルートへ分ける構成を検討するかを判断し、[proposal.md](../../proposal.md) 6章・8.1との整合を確認する。判断は記録し、必要なら後続プランへ回す。
- [ ] 翌年分の扱いを確認する。`photo-library/2027/2027-01/camera/` に相当するフォルダを作ってファイルを1件置き、対象の指定を変えずにAmazonへ上がることを確認する（A04）。確認後、そのファイルとフォルダは削除する。

### 段階6: 例外時の追従を確認する

- [ ] SMBを切断し、Amazon Photos Desktopがどう振る舞うか（停止するか、エラーを出すか、黙って対象を失うか）を確認する。再接続後にバックアップが再開することを確認する（A05）。
- [ ] Macを再起動し、段階1の永続化によってマウントとバックアップが自動で戻ることを確認する。マウント位置が変わらないことも確認する（A06）。
- [ ] スリープ復帰後の追従を確認する。
- [ ] コピー途中のファイルをAmazonが取り込まないことを確認する（A07）。`photo-copy` の一時ファイルはローカル転送が `.<最終名>.photo-copy-<16進>.part`、rsync over SSHがrsyncの既定の一時名であり、いずれもドットで始まる隠しファイルである（[src/photo_copy/local.py:54](../../../src/photo_copy/local.py#L54)）。大きめのファイルを転送しながらAmazon側の状態を観察する。
- [ ] 進捗と停滞を週次でまとめて確認する方法（アプリ内のどの画面で何を見るか）を決める。

### 段階7: 手順を正本へ反映する

- [ ] 配置に関わる正本を更新する。[docs/proposal.md](../../proposal.md) 4.1のフォルダ構成図（ライブラリルートを1階層下げた理由を含む）と7.1のImmichのマウント指定（`/mnt/camera_archive/photo-library:/external/photo-library:ro`）、[docs/setup/ubuntu.md](../../setup/ubuntu.md) の正本ルートの記述と手順4・6の説明、[docs/setup/mac.md](../../setup/mac.md) の試験用ディレクトリの置き場所（`ARCHIVE_MOUNT` 配下ではなくライブラリルート配下）、`scripts/mac/profiles.ini.example` を更新する。
- [ ] `docs/setup/mac.md` にSMBマウントの手順（スクリプトの実行と確認）と、Amazon Photos Desktopの手動手順（ログイン、対象フォルダの指定、動画除外、確認する画面）を追加する。現在の「Amazon Photos Desktopの設定は0008で追加する」の記述を置き換える。
- [ ] `docs/setup/README.md` の整備状況を更新する。
- [ ] iPhoneのAuto-Saveが無効であることを確認し、記録する。
- [ ] 0009・0010へ渡す前提（ライブラリルートの位置、Amazonの対象フォルダの指定、マウント方式、主HDDに残っているもの、残した未確認事項）を `validation.md` に明記する。

## 検討した代替案

段階2の方式として次を比較し、ライブラリルートの移動を採る。

| 案 | 内容 | 採否 |
|---|---|---|
| 年ごとに対象を追加する | 現状のまま、年が変わるたびにAmazon側で `2027` を追加する | 不採用。追加を忘れるとその年が黙って保護されない。日常を週次の進捗確認だけで済ませる方針に反する |
| 共有の親ディレクトリを公開する | Sambaの共有パスを `/mnt/camera_archive` の親へ変え、Macから1階層深く見せる | 不採用。親ディレクトリにはHDD以外のものが含まれ、共有範囲が広がる |
| バインドマウントで階層を足す | HDD側の配置は変えず、`/mnt/<別ディレクトリ>/CameraArchive` へバインドマウントし、そこを共有する | 不採用。実データを動かさずに済む一方、正本のパスとMacから見えるパスが食い違い、手順の説明が複雑になる。また未マウント時も対象フォルダが空のまま存在し続けるため、Amazonから見て「空のライブラリ」と区別できない |
| ライブラリルートを新設する（採用） | `/mnt/camera_archive/photo-library/` を正本のライブラリルートとし、年フォルダをその下へ置く | 採用。正本のパスとMacから見えるパスが一致する。未マウント時はライブラリルート自体が存在しないため、誤書込み防止の既存の判定をそのまま使える |

現在の主HDDの中身は0007のテストコピーだけであり、コピー元に原本が残っている。そのため実データを移動せず、段階2で削除してから新しいライブラリルートへ置き直す。どの案でもMacから見えるパスが変わるため、データを移動する場合は既存アップロード分の重複確認が必要になるが、削除して置き直すことでこの確認自体が不要になる。

## 検証項目

| ID | 区分 | 確認すること | 現況 |
|---|---|---|---|
| A01 | 基本 | JPEG・HEIC・ARW・現像済みJPEGがAmazonへ上がる | 上がっていることは利用者が確認済み。形式ごとの個別確認は未実施 |
| A02 | 基本 | 各形式をAmazonから再取得でき、元と一致する | 未着手 |
| A03 | 基本 | 動画がAmazonの対象外である | 未着手 |
| A04 | 基本 | 対象フォルダの指定が年をまたいでも漏れない | 未着手（現在は `2026` フォルダ固定。段階3で `photo-library` へ集約し、段階5で翌年分を確認する） |
| A05 | 基本 | SMB切断・再接続後にバックアップが再開する | 未着手 |
| A06 | 基本 | Mac再起動後にマウントとバックアップが自動で戻る | 未着手（永続化が未整備） |
| A07 | 基本 | コピー途中の一時ファイルをAmazonが取り込まない | 未着手 |
| A08 | 基本 | HDDから削除した写真がAmazonに残る（許容の確認） | 未着手 |
| A09 | 再構築 | SMBマウントをスクリプトで再現・判定できる | 段階1で導入・確認済み。再起動での復帰確認は段階6（A06）で行う |
| A10 | 再構築 | Amazon Photos Desktopの手動手順が `docs/setup/mac.md` にある | 未着手 |
| A11 | 基本 | iPhoneのAuto-Saveが無効である | 無効であると利用者が確認済み。記録のみ |
| A12 | 基本 | `photo-copy` が新しい既定の配置先へコピーでき、`check` と再実行時の同一スキップも従来どおり動く | 未着手 |
| A13 | 再構築 | ライブラリルートの作成をスクリプトで再現でき、未マウント時に存在しないことを判定できる | 未着手 |

## 完了条件

- A01〜A08、A12・A13の確認結果を `validation.md` に記録している。確認できなかった項目は、その形式・操作の運用判断を保留として明記している。
- 主HDDのライブラリルートが `/mnt/camera_archive/photo-library/` であり、年フォルダがその下にある。Amazonのバックアップ対象がこの1フォルダであり、年が変わっても指定を変えずに済む。
- ライブラリルートの変更が `scripts/`、`src/photo_copy/`、`tests/`、[docs/proposal.md](../../proposal.md)、`docs/setup/` に反映され、自動テストが通る。
- Mac側のSMBマウントが再起動後も自動で復帰し、`scripts/mac/` の導入スクリプトと確認スクリプトで再現・判定できる。
- `docs/setup/mac.md` にSMBマウントとAmazon Photos Desktopの手順があり、`docs/setup/README.md` の整備状況が実態と一致している。
- 0007のテストコピーを主HDDと `PhotoWork` から削除し、削除した内容とコピー元の所在を記録している。段階4で置き直した代表メディアだけがライブラリルートにある。
- 0009・0010へ渡す前提と未解決事項が明確である。
