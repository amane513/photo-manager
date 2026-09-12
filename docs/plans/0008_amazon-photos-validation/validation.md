# 0008 検証記録

## 2026-09-12: 段階1 Mac側のSMBマウントを永続化する

- 着手前の状態: `//amane-yajima@192.168.11.17/CameraArchive` が `/Volumes/CameraArchive` へ手動マウント済みだった。`~/.ssh/config` の `ubuntu` エイリアス（`192.168.11.17`）と同一ホストだが、SMBマウントはSSH設定を解釈しないため、ホスト設定に新たに `SMB_SERVER=192.168.11.17` を追加した（`scripts/hosts/ubuntu-amane-yajima.env`、`scripts/hosts/ubuntu.env.example`）。
- `security find-internet-password -a amane-yajima -s 192.168.11.17 -r "smb "` で、SMB認証情報が既にログインキーチェーンへ保存済みであることを確認した（過去にFinderで「パスワードをキーチェーンに保存」を選んで接続した結果と判断する）。新規のパスワード入力は不要だった。
- 永続化の方式は、ログイン項目（自動接続）とautofs（`/etc/auto_smb`）を比較し、ログイン項目を採用した。autofsは既定でアイドル時（未アクセス時、通常60分）に自動アンマウントされ、Amazon Photos Desktopが対象フォルダを黙って見失うリスクがplanの前提（バックアップが黙って止まらないこと）と直接衝突するため不採用とした。ログイン項目はマウント後は通常のSMBマウントとして常時見え、`/Volumes/CameraArchive` の位置も変わらない。
  - 実装は「ログイン項目」機能（System Settings > Users & Groups > Login Items）ではなく、`~/Library/LaunchAgents/` へのLaunchAgent登録とした。System Eventsを介したLogin Items操作はTCCの自動化許可（GUIでの手動許可）が必要になり、スクリプトだけで完結しないため。LaunchAgentは`RunAtLoad`で同等の「ログイン時に自動実行」を実現でき、権限プロンプトなしにスクリプトから冪等に設定できる。
- `scripts/mac/mount-camera-archive.sh`（マウント本体。既にマウント済みなら何もしない）、`scripts/mac/setup-smb-mount.sh`（LaunchAgentの導入。dry-run対応、冪等）、`scripts/mac/verify-smb-mount.sh`（マウント状態・読み書き可否・LaunchAgent登録の検査）を実装した。
- 実機で `setup-smb-mount.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env --dry-run` → 本実行の順で実行した。本実行時は既にマウント済みだったため「既にマウント済み」を表示して完了し、LaunchAgent（`com.photo-manager.mount-CameraArchive`）を `launchctl bootstrap` で読み込んだ。
- `verify-smb-mount.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env` が `OK` を返し、マウント・書き込み・LaunchAgent登録を確認した。
- 未マウントからの自動再接続（パスワード入力なしでの再マウント）は、`lsof` で確認したところ Amazon Photos Desktop（PID 58498）が `/Volumes/CameraArchive/2026/2026-08/camera/20260823-191612_DSC00306.ARW` を読み取り中で、Finderも同フォルダを開いていたため、実際の切断試験は行わなかった（`umount`が`Resource busy`で失敗）。この確認は段階6のSMB切断・再接続確認（A05）と重複するため、そこでまとめて行うこととし、段階1では保留とする。
- Mac再起動後にLaunchAgentが実際にマウントを復帰させることの確認も、段階6の再起動確認（A06）にあわせて行う。
- Ubuntu実機で、リポジトリに未追跡の `/usr/local/bin/photo-manager-finalize`（214バイト、root所有）と `/usr/local/lib/photo-manager-copy-finalizer/{0.2.0,0.2.1}/finalizer.py`（`--archive-root`配下で一時ファイルを`RENAME_NOREPLACE`で最終名へ確定するCLI。バックアップファイル`photo-manager-finalize.photo-manager.20260911203157.bak`あり）、および `/mnt/camera_archive/.photo-manager-volume-id`（`photo-manager-primary-0574e6d5-893c-41b5-84e8-77c41c3b59c1`、amane-yajima所有）を発見した。いずれも作成日時は2026-09-11で、現在のリポジトリのどのスクリプトからも参照されていない。利用者と確認し、0005の初期検討（サーバー側での一時ファイル確定処理、ボリューム識別マーカー）の残骸であり、現在はMac側の`local.py`・`rsync.py`による一時ファイル処理へ置き換わっていて不要と判断した。`.photo-manager-volume-id`は本人所有だったため削除した。`/usr/local/`配下のfinalizer一式はroot所有でsudoが必要なため、0008の中では削除せず、利用者へ削除コマンドを別途案内した（0008の完了条件には含めない）。

## 2026-09-12: 段階2 テストコピーを削除し、主HDDを空にする

- 削除前の主HDD `/mnt/camera_archive/` 配下の一覧（`find -printf`、`lost+found`は権限がなく列挙不可）を取得した。実写真・動画は12件だった。
  - `2026/2026-08/camera/`: `20260822-184717_DSC00241.JPG`、`20260823-191559_DSC00305.{ARW,ARW.xmp,_edit.jpg,JPG}`、`20260823-191612_DSC00306.{ARW,ARW.xmp,_edit.jpg}`、`20260830-122104_C0006.MP4`
  - `2026/2026-09/smartphone/`: `20260912-153734_IMG_1525.HEIC`、`20260912-153742_IMG_1526.MOV`、`20260912-153751_IMG_1527.{HEIC,MOV}`
  - ほかmacOSが作った`._*`・`.DS_Store`が11件。
- コピー元の確認: `DSC00241`・`DSC00305`・`DSC00306`のARW/JPGと`C0006.MP4`はMacの`~/Pictures/backup/DCIM/100MSDCF/`・`~/Pictures/backup/PRIVATE/M4ROOT/CLIP/`に原本が残っていることを確認した（`.xmp`と`_edit.jpg`はdarktableによる派生物であり、元のARWが残っていれば再現できる）。`IMG_1525`・`IMG_1526`・`IMG_1527`の原本はiPhone本体にあり、plan.mdの「決まっていること」の前提に従い個別の再確認はしなかった。SDカードは現在Macに未挿入だった。
- まず `20260822-184717_DSC00241.JPG` と `20260912-153734_IMG_1525.HEIC` の2件を主HDDから削除し、Amazon Photos側（アプリ／Web版）で検索して両方とも残っていることを利用者に確認してもらった（A08）。削除の伝播がないことを実機で確認した。
- 残りの写真・動画10件と`._*`・`.DS_Store`11件を削除し、空になった`2026/2026-08/camera`・`2026/2026-08`・`2026/2026-09/smartphone`・`2026/2026-09`・`2026`ディレクトリを`rmdir`で削除した。`lost+found`は写真以外のext4標準ディレクトリのため残した。
- `.photo-manager-volume-id`（段階1の脚注参照）もあわせて削除した。削除後、`/mnt/camera_archive/`直下は`lost+found`のみになった。
- Macの`~/Pictures/PhotoWork/`からも同じテストコピー一式（`DSC00241.JPG`、`DSC00306`一式、`C0006.MP4`、0007の複数月確認で残っていた`DSC00456.ARW`、`IMG_1525.HEIC`、`IMG_1526.MOV`）と`.DS_Store`を削除し、空になった年月・機器別フォルダも削除した。`DSC00456.ARW`は主HDDには到達しておらずPhotoWorkにのみ残っていたが、原本は`~/Pictures/backup/DCIM/100MSDCF/DSC00456.{ARW,JPG}`に確認できたため削除した。PhotoWorkの選別で先に間引かれていた`DSC00305`一式・`IMG_1527`一式（0007のvalidation.md参照）は、この時点でPhotoWorkには元から存在しなかった。
- Amazon Photos側の全削除は利用者が先行して実施した。削除前のアプリ上の件数は未確認のまま削除された（保留事項として記録する）。削除後、Amazon側は写真0件になったことを利用者が確認した。削除したファイルはゴミ箱に90日間保管され、期間内は復元可能とアプリ上で確認した。
- 以降は「Amazonに存在する＝新しいライブラリルート（`photo-library`）から上がった」と一意に判定してよい状態になった。

未確認事項: Amazon Photos削除前の件数（写真・動画の内訳を含む）は記録できていない。ローカルに原本がないと思われるもの（旧Macフォルダ由来等）の有無も個別確認していない。実害はない（利用者判断で全削除済み、原本は主HDD・`~/Pictures/backup/`・iPhone本体に別途ある）が、完了条件の記録としては保留として明記する。

## 2026-09-13: 段階3 ライブラリルートを新設し、CLIとスクリプトを追従させる

- ホスト設定に `ARCHIVE_LIBRARY_ROOT=/mnt/camera_archive/photo-library` を追加した（`scripts/hosts/ubuntu-amane-yajima.env`、`scripts/hosts/ubuntu.env.example`）。
- `scripts/ubuntu/setup-library-root.sh` を実装し、実機で `--dry-run` → 本実行 → 本実行（2回目）の順で実行した。1回目で `install -d -o amane-yajima -g amane-yajima -m 0755 /mnt/camera_archive/photo-library` を実行して作成し、2回目は「既存のライブラリルートは設定済み」で冪等に終了した。
- `scripts/ubuntu/verify-primary-storage.sh` にライブラリルートの存在・所有者・権限の判定を追加し、実機で `OK: 主HDD、fstab、ライブラリルート、権限、Sambaサービスを確認した。...ライブラリルート: /mnt/camera_archive/photo-library` を確認した。
- `scripts/ubuntu/verify-unmounted-primary-storage.sh` に、未マウント時にライブラリルートが存在しないことの判定を追加した。実機での確認は、`/mnt/camera_archive` が稼働中のsmbd（Macの接続セッション）に掴まれて`umount`が`target is busy`で失敗したため、今回は見送った。Mac側から`/Volumes/CameraArchive`を切り離そうとしたが、`lsof`上は何も掴んでいないにもかかわらず`umount`・`diskutil unmount`とも`Resource busy`で失敗した（Spotlight索引等が原因の可能性）。この確認は段階6のSMB切断確認（A05）にあわせてUbuntu側のumountもまとめて行うこととし、保留とする。
- `src/photo_copy/hosts.py` に `archive_library_root` を追加し、`ARCHIVE_LIBRARY_ROOT` を必須項目にした。`ARCHIVE_MOUNT` 配下にない場合は読み込み時に `ValueError` にする検証を追加した。
- `src/photo_copy/cli.py` の `copy`・`check` 双方で、`--destination-root` 省略時の既定を `ARCHIVE_MOUNT` から `ARCHIVE_LIBRARY_ROOT` へ変更した。
- `src/photo_copy/rsync.py` の事前検査を、配置先ルートが `ARCHIVE_LIBRARY_ROOT` 配下であることを判定するように変更した（`ARCHIVE_MOUNT` 直下だが `ARCHIVE_LIBRARY_ROOT` 外の旧来の年フォルダ配置は拒否する）。マウント済み判定は従来どおり `ARCHIVE_MOUNT` に対して行う。
- `tests/` を更新し（`test_hosts.py`、`test_rsync.py`、`test_cli.py`）、`.venv/bin/python -m unittest discover -s tests` が113件すべて成功することを確認した。
- 実機で `photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env` を実行し、`OK: 接続先 ubuntu、配置先ルート /mnt/camera_archive/photo-library、...` と、新しい既定の配置先で成功することを確認した（A12）。Macから `/Volumes/CameraArchive/photo-library/` が見えることも確認した（作成直後は空）。
- Amazon Photos Desktopのバックアップ対象を「2026」フォルダから「photo-library」フォルダへ利用者が切り替えた。切替時点で中身は空だった。画面表記の詳細記録は省略し、切替完了の事実のみを記録する。

## 2026-09-13: 段階4 代表メディアを置き直し、形式ごとのアップロードと再取得を確認する

- SDカードから `DSC01139.{ARW,JPG}`（ARW+JPEGの組）と `PRIVATE/M4ROOT/CLIP/C0014.MP4`（動画）を、`--only` で3件に絞って `photo-copy copy --transport rsync-ssh`（`--destination-root` 省略）で主HDDへ配置した。`photo-library/2026/2026-09/camera/` に配置され、`--destination-root` の新しい既定がライブラリルート配下になることを確認した（A12）。動画は805MBあり、rsync転送がツールのコマンドタイムアウトを超えたためバックグラウンド実行で完了を確認した。
- iPhoneからイメージキャプチャで `~/Pictures/PhoneImportInbox/iphone/` へHEIC単体1枚（`IMG_1525.HEIC`）とLive Photoの組1組（`IMG_1527.HEIC`+`.MOV`）を取り込み、`--device smartphone --transport local` でPhotoWorkへ分類後、`--layout preserve --transport rsync-ssh`（`--destination-root` 省略）で主HDDへ転送した。同じく `photo-library/2026/2026-09/smartphone/` に配置され、新しい既定の配置先で成功した。取り込み後 `PhoneImportInbox/iphone/` は空に戻した。
- 配置した `20260912-111423_DSC01139.ARW` をdarktableでSMB経由で直接現像し、同じ `camera/` に `.xmp` と `_edit.jpg` を生成した（0007と同じ手順）。macOSが作った `._*` 補助ファイルと、rsyncで持ち込まれた `.DS_Store`／`._.DS_Store` は削除した。
- 最終的にライブラリルートへ置いたのは、JPEG（撮って出し）・ARW・XMP・現像済みJPEG・動画（MP4）・HEIC単体・Live Photo（HEIC+MOV）の7種8ファイルである。年フォルダの追加操作はしておらず、Amazon側の対象指定は「photo-library」のままである。
- Amazon Photos上で、配置した代表メディアのうちJPEG・ARW・現像済みJPEG・HEIC単体・HEIC（Live Photo側）の5件がアップロードされていることを利用者が確認した（A01）。動画の扱いは段階5で確認する。
- 上記5件をAmazonから `~/Downloads/AmazonPhotos/` へダウンロードし、SHA-256とサイズを主HDD上の実体と比較した。5件とも完全に一致した（A02）。
  - `20260912-111423_DSC01139.ARW`: `79bfb027f86cc9c48af005c87281940de01c051d1339358535982a98d9139a3d`
  - `20260912-111423_DSC01139.JPG`: `0a05e9430765c9bc232838ea71d93ee709afa73bdc45fcd9da9c56c7dcbf99b8`
  - `20260912-111423_DSC01139_edit.jpg`: `977872a829ef2b8726e487ae08f97385ac7f7e40095c2e14b4cc25c942c495a4`
  - `20260912-153734_IMG_1525.HEIC`: `e9c157c94e20c45907e4ecdf83346e97cc6271f0ac698af86f00f5dcd5eb27a6`
  - `20260912-153751_IMG_1527.HEIC`: `6b791605ed8aa1eb0951841ed431f1c29bd5ca0fa2276ca2eb46b4c8e2577071`
- ダウンロードした5件はすべて問題なく開けることを利用者が確認した。HEICの表示・再取得もJPEGと同等に扱え、差異は見られなかった。
- SDカードからのコピーとPhotoWork→HDDの転送を同じコマンドで再実行し、いずれも「スキップ3件」で内容一致による同一スキップが動くことを確認した（A12、rsync-ssh経由）。

## 2026-09-13: 段階5 動画除外と対象範囲を確認する

- 段階4で配置した動画（`C0014.MP4`、Live Photoの`IMG_1527.MOV`）がAmazon Photosに上がっていないことを利用者に確認してもらった（A03）。動画は年月・機器別フォルダの中に静止画と混在しているが、アプリ側で自然に除外されており、除外設定の追加操作は不要だった。動画をAmazon対象外にする方針と衝突する事象は発生しなかった。
- 翌年分の確認として、`~/Pictures/PhotoWork/2027/2027-01/camera/photo-library-test-2027.JPG`（テスト用ファイル、`DSC01139.JPG`を複製・改名したもの）を作成し、`--layout preserve --transport rsync-ssh`（`--only 2027/2027-01/camera`）で主HDDの `photo-library/2027/2027-01/camera/` へ配置した。Amazon Photos Desktopの対象フォルダ一覧が「photo-library」のままで変更不要であり、かつ新しく置いたファイルがアップロードされることを利用者に確認してもらった（A04）。年をまたいでも対象指定を変えずに済むことを実機で確認した。
- 確認後、テストファイルと空になったディレクトリ（`2027/2027-01/camera`、`2027/2027-01`、`2027`）を主HDD・PhotoWork双方から削除した。Amazon側には方針どおり残したままにした（削除の伝播はしない）。

## 2026-09-13: 段階6 例外時の追従を確認する

- **SMB切断・再接続（A05）**: `diskutil unmount /Volumes/CameraArchive` でMac側から切断した。Amazon Photos Desktopは「DISCONNECTED」と明示表示し、エラーで落ちたり無反応になったりはしなかった。Ubuntu側の`umount`は、切断直後は古いsmbdワーカープロセス（クライアント切断後も`cwd`がマウント内に残っていた）に掴まれて`target is busy`になったため、該当プロセスをkillしてから再試行した。これにより段階3で保留していたUbuntu側の未マウント確認（A13）も完了した: `verify-unmounted-primary-storage.sh`が`OK: 未マウント時、/mnt/camera_archive は amane-yajima による書込みを拒否し、ライブラリルートも存在しない。`を返した。再マウント後、Mac側は`mount-camera-archive.sh`実行時点で既に自動再接続しておりパスワード入力は不要だった（段階1の保留事項も解消）。`verify-smb-mount.sh`もOKを返した。
  - ただし、Amazon Photos Desktop自体はSMB復旧を自動検知せず「DISCONNECTED」表示のままだった。利用者がアプリを再起動したところ「BACKUP COMPLETE」に変わり、バックアップが再開した。**自動での再開はしない**という重要な挙動上の制約であり、週次確認の手順に反映する（後述）。
- **コピー途中の一時ファイル（A07）**: SDカードから未取り込みのARW+JPEG30件（15組）を`--transport rsync-ssh`で転送しながら、Ubuntu側を直接観測した。転送中に `.20260823-192648_DSC00316.ARW.brXSPu` のようなrsync既定の一時名（ドット始まり）が実際に存在することを確認した。Mac側のSMBマウント経由でも、通常の`ls`（`-a`なし）ではこの一時ファイルが見えず、`-a`を付けたときだけ見えることを確認した。転送中、Amazon Photos Desktopのアップロード履歴・キューには一時ファイルらしきものやエラーは見られなかった（利用者確認）。転送完了後、`find -name ".*"`でrsyncの一時ファイルが残っていないことを確認した（残っていたのはdarktableのSMB書き込みに伴う`._*`のAppleDoubleファイルのみで、0007から許容している既知の事象である）。
- **スリープ復帰**: Macをスリープさせ復帰させたところ、SMBマウントとAmazon Photos Desktopのバックアップは問題なく継続した（利用者確認）。
- **Mac再起動（A06）**: 利用者がMacを再起動した後、新しいセッションで確認した。`uptime`が「up 3 mins」であることから再起動直後であることを確認したうえで、`/Volumes/CameraArchive`が既に自動マウントされていること（`mount`コマンドとLaunchAgentのログで確認。`mount-camera-archive.sh`が「マウントした」を記録していた）、マウント位置が `/Volumes/CameraArchive` のまま変わっていないこと、`verify-smb-mount.sh`がOKを返すことを確認した。Amazon Photos Desktopもバックアップを自動で再開した（利用者確認、手動でのアプリ起動は不要だった）。
- **週次の進捗・停滞確認方法**: Amazon Photos Desktopのメイン画面の状態表示（「BACKUP COMPLETE」/「DISCONNECTED」等）を見るだけで足りることを確認した。「DISCONNECTED」表示を見つけた場合は、SMB再接続だけでは自動回復しないため、**アプリ自体を再起動する**ことを手順として明記する。週次でこの画面を開き、正常表示でなければアプリを再起動する、という運用でよい。

## 2026-09-13: 段階7 手順を正本へ反映する

- [docs/proposal.md](../../proposal.md) 4.1（ライブラリルートを1階層下げた理由を含むフォルダ構成の説明）、6章（Amazon Photosの対象指定・動画除外・DISCONNECTED時の再起動が必要という挙動）、7.1（Immichのマウント指定を `/mnt/camera_archive/photo-library:/external/photo-library:ro` へ）を更新した。
- [docs/setup/ubuntu.md](../../setup/ubuntu.md) の前提（ライブラリルートの位置と新設理由）を更新し、手順4として `setup-library-root.sh` を追加した（以降の手順番号を1つずつ繰り下げた）。手順5（検査）・7（未マウント確認、旧6）の説明にライブラリルートの判定を追記し、smbdワーカーがマウントを掴んで`umount`が失敗する場合の対処（段階6で実機確認した手順）も追記した。
- [docs/setup/mac.md](../../setup/mac.md) に手順8（SMB共有の自動マウント設定、`setup-smb-mount.sh`／`verify-smb-mount.sh`）と手順9（Amazon Photos Desktopの手動設定：ログイン、対象フォルダの指定、動画除外の実態、週次確認とDISCONNECTED時のアプリ再起動）を追加した。手順5の `--destination-root` 省略時の既定説明と、隔離試験先の置き場所を `ARCHIVE_LIBRARY_ROOT` 配下へ更新した。
- [scripts/mac/profiles.ini.example](../../../scripts/mac/profiles.ini.example) に、`destination-root` 省略時は `ARCHIVE_LIBRARY_ROOT` が既定になる旨のコメントを追加した（値自体の変更は不要）。
- [docs/setup/README.md](../../setup/README.md) の整備状況表を更新し、「Mac側のSMBマウントの永続化」「Amazon Photos Desktopの設定」を整備済みにし、「主HDDのマウント・権限・SMB共有」の行にライブラリルートと0008を追記した。
- iPhoneのAmazon Photos Auto-Saveが無効であることは、0008着手前から利用者が確認済みである（plan.mdの「現状」・検証項目A11参照）。0008では新たな設定変更は行わず、無効であることの確認記録のみを残す。

### 0009・0010へ渡す前提

- **ライブラリルートの位置**: 主HDDの正本は `/mnt/camera_archive/photo-library/` である。年フォルダはこの下に置く（`/mnt/camera_archive/` 直下ではない）。Macからは `/Volumes/CameraArchive/photo-library/...`。
- **Amazonの対象フォルダ**: 「photo-library」の1フォルダのみを指定済みであり、年が変わっても対象指定の変更は不要である。動画（MP4/MOV）はアプリ側で自然に除外される。
- **マウント方式**: MacのSMBマウントはLaunchAgent（`~/Library/LaunchAgents/com.photo-manager.mount-CameraArchive.plist`）でログイン時に自動接続する。マウント位置は `/Volumes/CameraArchive` のまま変わっていない。`scripts/mac/setup-smb-mount.sh`・`verify-smb-mount.sh` で再現・判定できる。
- **主HDDに残っているもの**: `photo-library/2026/2026-09/` 配下に、段階4・6で配置した代表メディア・確認用メディア（ARW・JPEG・XMP・現像済みJPEG・動画・HEIC・Live Photoの組、および段階6のA07確認で転送した15組のARW+JPEG計30件）がある。これらは0008の実機確認の過程で配置したものであり、0007のような「削除前提のテストコピー」ではなく実データ（SDカード原本のコピー）である。0009で実運用規模の取り込みを始める際、そのまま正規の取り込み分として扱ってよい。
- **未解決事項**:
  - Amazon Photos Desktopは、SMB復旧を自動検知せずアプリの再起動が必要という挙動が判明した（Mac再起動時は自動復帰した。A05の切断・再接続の場合に限る既知の制約）。0009以降の日常運用でも、週次確認時にこの点を踏まえる。
  - Amazon Photos削除前の件数（写真・動画の内訳）は記録できなかった（段階2参照）。実害はないが、完了条件としては保留のままである。

## 2026-09-13: A06（Mac再起動後の自動復帰）確認

- 利用者がMacを再起動した。新しいセッションで `uptime` が「up 3 mins」であることを確認し、再起動直後であることを確認した。
- `/Volumes/CameraArchive` は既に自動マウントされており、マウント位置も変わっていなかった。`~/Library/Logs/photo-manager-mount-CameraArchive.log` に、LaunchAgentの`RunAtLoad`によって`mount-camera-archive.sh`が実行され「マウントした: /Volumes/CameraArchive」と記録されていた。`verify-smb-mount.sh --host-config ./scripts/hosts/ubuntu-amane-yajima.env` もOKを返した。
- Amazon Photos Desktopのバックアップも、利用者の手動操作なしに自動で再開していることを確認した（利用者確認）。
- これによりA06・A09が確認済みとなり、0008の全項目が完了した。
