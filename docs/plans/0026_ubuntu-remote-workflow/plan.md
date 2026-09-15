# 0026: Ubuntuリモート作業ルールの明文化

作成日: 2026-09-15

更新日: 2026-09-15

状態: 完了（作業指示の更新）

## 目的

LAN外からもUbuntuへ確実に接続できるようSSHエイリアスの優先順位を共有し、実機作業のためにUbuntu側リポジトリへ未コミット差分が残ることを防ぐ。

## 判断

このルールは特定作業でだけ呼び出すワークフローではなく、このリポジトリを扱う全エージェントへ常時適用する必要がある。そのためskillではなく、CodexとClaude Codeが共有する `AGENTS.md` に記載する。

## 変更内容

- SSHは最初に `ssh ubuntu`、接続できない場合に `ssh ubuntu_by_tailscale` を試す。
- 編集・コミット・pushはMac側で行い、Ubuntu側はcleanなmainをfast-forwardするだけとする。
- Ubuntuのcheckoutへファイルを直接転送・適用しない。
- Ubuntuでの作業前後にdirty状態とorigin/mainへの追従を検査する。
- dirty状態を検出した場合は別セッションの変更を保護するため自動修復せず停止する。

## 完了条件

- [x] 接続先の優先順位が `AGENTS.md` に記載されている。
- [x] Macからcommit経由でUbuntuへ反映するルールが記載されている。
- [x] Ubuntuの作業前後にclean状態を検査するルールが記載されている。
- [x] CodexとClaude Codeの共有設定を検証する。
