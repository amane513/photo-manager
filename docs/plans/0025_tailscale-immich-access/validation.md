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

## 未完了の検証

- sudoで更新後のCompose定義を `/srv/immich/app/` へ反映し、Immichコンテナを再作成する。
- Tailscale Serveを設定し、`verify-tailscale-immich.sh` を成功させる。
- iPhoneのモバイル回線からSafariとImmichアプリで閲覧し、Tailscale無効時には接続できないことを確認する。
