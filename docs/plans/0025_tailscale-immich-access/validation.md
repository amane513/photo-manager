# 0025 検証記録

検証日: 2026-09-15

## 実機の事前状態

- Macから `ssh ubuntu_by_tailscale` でUbuntu常時稼働PCへ接続できた。
- UbuntuではTailscale 1.102.2とtailscaledが稼働し、Tailscale IPv4アドレスは `100.66.37.84` であった。
- 同じtailnet上で `iphone-13` がオンラインであることを確認した。
- Tailscale Serveは未設定であった。
- Immichの4コンテナは稼働中で、Immich serverは `192.168.11.17:2283` だけに公開されていた。`127.0.0.1:2283` では待ち受けていなかった。
- Ubuntuのsudoはパスワード入力を必要とするため、非対話SSHから実行時ComposeやServeの設定は変更していない。

## 実装検証

- Bashの構文検査に成功した。
- Ubuntu上のDocker Composeを使い、秘密値を含まない `immich.env.example` から更新後のCompose定義を展開できた。
- `git diff --check` に成功した。
- Ubuntu側リポジトリの既存未コミット変更を保持し、今回のCompose差分と検査差分を `git apply --check` 後に適用した。新規Tailscaleスクリプトも配置した。

## 初回適用時の修正

更新後のImmichコンテナを再作成した直後、Tailscale設定スクリプトのloopback確認が `Recv failure: Connection reset by peer` で停止した。その後の調査では、LAN側とloopback側の両方がHTTP 200を返し、Immich serverもhealthyであった。Dockerのport bindingも想定どおりであり、起動完了前に1回だけ接続確認したことが原因であった。

コンテナ再作成直後にも安全に実行できるよう、loopback確認を最大60秒再試行するよう修正した。

## Tailscale Serveの検証

- Tailscale Serveの初回利用をtailnet管理画面で許可し、Ubuntu上の利用者 `amane-yajima` をTailscale operatorに設定した。
- `https://amane-yajima-ms-7d32.tail5bc3b9.ts.net/` から `http://127.0.0.1:2283` へのtailnet内限定プロキシを設定した。
- 初回のACME証明書発行中はTLSハンドシェイクが待機したが、tailscaledのログで証明書取得完了を確認した後、MacとUbuntuの両方からHTTPS 200と証明書検証成功を確認した。
- Ubuntuからオンラインの `iphone-13` へTailscale pingが38msで成功した。
- `verify-tailscale-immich.sh` にServe URLへのHTTPS接続確認を追加した。
- iPhoneを外部ネットワークへ接続し、SafariとImmichアプリの両方からServe URLで写真を閲覧できることを確認した。確認直後、Ubuntu上のTailscale状態では `iphone-13` に約6.7MBの送信が記録されていた。
- Immichアプリでは当初、Current Server Addressに家庭内LANのIPが残り、高解像度画像を表示できなかった。アプリを再起動した後は高解像度画像まで正常に表示できた。
- `tailscale serve status` でHTTPS URLがtailnet限定であることを確認した。Immichの2283番ポートは家庭内LAN IPとloopbackだけにbindされ、Tailscale IPへ直接公開されていない。これらの構成検査を、iPhoneでTailscaleを無効にする個別の遮断試験に代えた。
