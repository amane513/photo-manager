# 0011 検証記録

実施日: 2026-09-13

## 実機の事前調査

- ホスト: `amane-yajima-MS-7D32`、Ubuntu 24.04.4 LTS、x86_64、RAM 31 GiBである。
- `/srv` を含む内蔵SSDはext4で、447 GiB空いている。
- 主HDDはUUID `0574e6d5-893c-41b5-84e8-77c41c3b59c1` に対応する`/dev/sda1`であり、`/mnt/camera_archive`へext4・read-writeでマウントされている。ライブラリルートは`/mnt/camera_archive/photo-library`であり、シンボリックリンクではない。
- GPUはdevice 0のNVIDIA GeForce RTX 4060 Ti 16 GiB、ドライバーは580.173.02である。
- Docker 29.7.1、Docker Compose v5.3.1、NVIDIA Container Toolkit 1.19.1、Dockerの`nvidia` runtimeを確認した。
- `/srv/immich`は未作成であり、ImmichまたはImmich PostgreSQLコンテナは存在しない。既存のComfyUIコンテナはlocalhostだけで待ち受けており、2283番ポートとの競合は確認されなかった。

## 配布物と実装

- 2026-09-13時点の最新安定版として`v3.2.0`を採用し、RC版ではないことを公式リリースノートで確認した。
- 公式v3.2.0の`docker-compose.yml`、`example.env`、`hwaccel.ml.yml`を基に、SSD配置、LAN bind、External Libraryのread-only mount、CUDA機械学習、永続モデルキャッシュの差分を`scripts/ubuntu/immich/`へ実装した。
- `bash -n`、`git diff --check`は成功した。
- CPU構成のコンテナ起動とhealth確認に成功した。CUDA構成へ切り替え後、コンテナ内のONNX Runtimeで`CUDAExecutionProvider`を確認した。Smart Search処理時にも同providerをログで確認した。
- ホスト公開用の`IMMICH_PORT=2283`がMLコンテナへ継承され、ML APIが3003番ではなく2283番で待ち受ける不具合を検出した。ComposeでMLコンテナの`IMMICH_PORT`を3003へ明示し、CUDA構成を再作成して解消した。

## 初期設定と処理結果

- 初期管理ユーザーをWeb UIで作成した。モバイル自動アップロード、外部公開、ストレージテンプレートは有効にしていない。
- Smart Searchモデルを`XLM-Roberta-Large-ViT-H-14__frozen_laion5b_s13b_b90k`へ設定した。
- External Library `photo-library`を初期管理ユーザー所有で作成し、コンテナ内パス`/external/photo-library`を登録した。除外パターン`**/*.ARW`および`**/*.arw`を設定してからスキャンした。
- 全メディアの表示を確認し、Smart Searchは失敗0件で完了した。CUDA providerのログを確認した。
- Immich標準機能でDBダンプを生成した。ファイルは`immich-db-backup-20260913T203622-v3.2.0-pg14.19.sql.gz`、サイズは21,595,089バイト、SHA-256は`eb9c9d0fbbacf5fd6b75a755388576cb3978ac3e79dcc95f1e8b86a675b48192`である。gzip検査に成功した。

## 未完了と理由

- UbuntuへのSSHは非対話実行であり、sudoが端末からのパスワード入力を要求したため、変更を伴う`setup-immich.sh`は実行していない。
- 検索評価は、日本語5件、英語または日英混在3件を実施し、いずれも期待する写真が上位20件に含まれた。検索語および写真内容は記録しない。
- DBダンプは同じSSD上にしかない。0012の復元試験および0013の第2 HDDへの保全は未実施である。
