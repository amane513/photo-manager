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
