# 0025: Tailscale経由のImmich閲覧

作成日: 2026-09-15

更新日: 2026-09-15

状態: 完了

## 目的

iPhoneから家庭内LANの外でもImmichを閲覧できるようにする。Immichのポートをインターネットへ直接公開せず、許可した端末だけが接続できる構成とする。

## 方針

- UbuntuとiPhoneを同じTailscaleのtailnetへ参加させる。
- 家庭内LANの既存URLを維持し、ImmichをTailscale Serve用の `127.0.0.1:2283` にもbindする。
- Tailscale ServeでloopbackのImmichをtailnet内限定のHTTPS URLへ転送する。
- ルーターのポート開放と、インターネットへ公開するTailscale Funnelは使わない。
- Tailscaleの端末制御に加えてImmichの既存ユーザー認証も維持する。

## 変更内容

- 閲覧要件と提案書へ、iPhoneからのリモート閲覧と非公開方針を追加する。
- ImmichのCompose定義へloopback bindを追加する。
- Tailscaleの導入・接続・Serve設定を行う冪等な構築スクリプトを追加する。
- tailscaled、tailnet接続、loopbackのImmich、Serve転送先を検査するスクリプトを追加する。
- UbuntuとiPhoneの実行手順、停止方法、紛失時の対応を正本へ追加する。

## 完了条件

- [x] `setup-tailscale-immich.sh` と `verify-tailscale-immich.sh` の構文検査が成功する。
- [x] 既存の家庭内LAN bindに加えてloopback bindをCompose定義へ追加する。
- [x] ルーターのポート開放とFunnelを使わない方針を正本へ記録する。
- [x] Ubuntuで更新後のImmich構成を起動し、LAN URLとloopbackの両方で応答を確認する。
- [x] Ubuntuをtailnetへ参加させ、検査スクリプトが成功する。
- [x] iPhoneのモバイル回線からSafariとImmichアプリの両方で閲覧できる。
- [x] Serve URLがtailnet限定であり、ImmichがTailscale IPへ直接bindされていないことを確認する。

## 参考資料

- [Tailscale: Install Tailscale on Linux](https://tailscale.com/docs/install/linux)
- [Tailscale: Install Tailscale on iOS](https://tailscale.com/docs/install/ios)
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)
- [Tailscale serve command](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Immich: Mobile App](https://docs.immich.app/features/mobile-app/)
