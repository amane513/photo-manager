# 環境の再構築手順

新しいPCで写真・動画管理環境を組み直すための手順を保存する。PC入れ替えのほか、故障やOS再インストールからの復旧にも使う。

方針は [proposal.md](../proposal.md) の「環境構築の再現性」を参照する。自動化した実体は [scripts/](../../scripts/) に置き、ここでは実行順、前提、自動化できない操作、確認方法を扱う。

## ホスト別の手順

- [ubuntu.md](ubuntu.md): 常時稼働PC。主HDDのマウントと共有、SSH・rsyncの受入れ、Immich、第2 HDDへのバックアップ。
- [mac.md](mac.md): MacBook Air。取り込みと現像のツール、SSH・rsyncの送信設定、SMBマウント、取り込みCLI、Amazon Photos。

入れ替える側のホストの手順だけを実行する。両方を同時に組み直す場合は、Ubuntu側を先に整えてからMac側を接続する。

## 使い方

1. 対象ホストの手順書を開き、前提と手動作業を確認する。
2. `scripts/hosts/` の該当ファイルに、そのホストの値（HDDのUUID、マウント先、共有名、利用アカウント）を設定する。
3. 手順書の順にスクリプトを実行する。まずdry-runで変更内容を確認する。
4. 確認用スクリプトを実行し、想定した状態になったことを判定する。

## 整備状況

各手順は対応するプランの実施時に作成する。未整備の項目は新しいPCでそのまま再現できない。

| 範囲 | 状態 | 対応プラン |
|---|---|---|
| 主HDDのマウント・権限・SMB共有・ライブラリルート | 整備済み | [0005](../plans/0005_primary-storage-setup/plan.md)・[0008](../plans/0008_amazon-photos-validation/plan.md) |
| SSH・rsyncによる取り込みCLIの導入 | 整備済み | [0006](../plans/0006_copy-cli-foundation/plan.md) |
| 第2 HDDへのバックアップ | 未整備 | 0013 |
| Immichの導入 | 整備済み | 0011 |
| Mac側のSMBマウントの永続化 | 整備済み | [0008](../plans/0008_amazon-photos-validation/plan.md) |
| Amazon Photos Desktopの設定 | 整備済み | [0008](../plans/0008_amazon-photos-validation/plan.md) |
| 日常の取り込み運用手順 | 未整備 | 0009 |
