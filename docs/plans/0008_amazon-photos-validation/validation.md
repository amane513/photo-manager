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
