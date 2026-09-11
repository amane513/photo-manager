# Ubuntu常時稼働PCの構築手順

主HDDの接続と共有、Immich、第2 HDDへのバックアップを担当するホストの手順である。全体の流れは [README.md](README.md) を参照する。

## 前提

- Ubuntu 64-bitをインストール済みで、sudoを実行できるアカウントがある。
- 4TB主HDDを接続している。正本のルートは `/mnt/camera_archive` とする。
- Immichの作業データとPostgreSQLは内蔵SSDの `/srv/immich/` に置く。

## 手動で行う作業

- 主HDDと第2 HDDの物理的な接続。
- 新しいHDDを使う場合のフォーマット判断。既存のデータがあるHDDを自動でフォーマットしない。

## 手順

未整備である。[0005](../plans/0005_primary-storage-setup/plan.md) の実施時に、主HDDのマウント、権限、Samba共有の手順とスクリプトを追加する。Immichは0011、第2 HDDへのバックアップは0010で追加する。
