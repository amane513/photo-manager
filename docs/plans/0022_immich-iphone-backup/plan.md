# 0022: ImmichによるiPhone直接バックアップ

作成日: 2026-09-13

更新日: 2026-09-13

状態: 未着手

## 目的

iPhoneの写真・動画を選別せず保存する運用を前提に、イメージキャプチャとMac上の作業フォルダを経由する取り込みを、ImmichモバイルアプリからUbuntuの主HDDへ直接アップロードする経路へ置き換える。iPhoneの日常的な取り込み操作を減らしながら、原本、Immich DB、Amazon Photos、第2 HDDを含む現在の保全方針を維持する。

## 前提

- 0011でExternal Libraryの全メディアを問題なく閲覧できていること。
- 0013で主HDD上の原本とImmich DB・設定を第2 HDDへ保存し、DBダンプを含めて復元できること。
- Sonyカメラは引き続き `photo-copy` で `/mnt/camera_archive/photo-library/` へ取り込み、Immichからread-onlyのExternal Libraryとして参照する。
- iPhoneからのバックグラウンドアップロードはiOSが実行時期を管理するため、即時完了を前提にしない。

## 採用する構成案

```text
Sonyカメラ ─ photo-copy ─> 主HDD/photo-library
                              └─> Immich External Library（read-only）

iPhone ─ Immich Mobile Backup ─> 主HDD上のImmich Upload Library
                                      ├─> Amazon Photos（静止画）
                                      └─> 第2 HDD（写真・動画）

Immich DB・設定・サムネイル・変換済み動画 ─> Ubuntu内蔵SSD
```

主HDD上のImmich管理領域は既存の `photo-library/` と分離する。ImmichのUpload LibraryをExternal Libraryと重ねず、アップロードされた原本のファイルをImmich外から移動・改名・削除しない。具体的なホストパスとコンテナ内マウントは、公式Compose構成と現在の `/srv/immich/` 配置を確認して実装時に確定する。

## 変更内容

### 1. 保存場所

- ImmichがiPhoneから受け取る写真・動画の原本を主HDDへ保存する。
- PostgreSQL、サムネイル、機械学習モデル、変換済み動画は内蔵SSDへ残す。
- アップロード中の一時ファイルと保存後の原本がどのパスに置かれるかを確認し、必要な全パスを容量監視とバックアップの対象にする。
- 主HDDが未マウントの場合はImmichを起動またはアップロード可能な状態にせず、SSD上の同名ディレクトリへ誤書込みしない。

### 2. iPhone取り込み

- Immichモバイルアプリで対象アルバムとWi-Fi時のバックアップを設定する。
- HEIC、JPEG、MOV、Live Photoの写真・動画ペア、編集済み写真、撮影日時と位置情報が原本どおり保存されることを確認する。
- 初回全件アップロードと、その後の差分アップロードを分けて実施する。
- アプリを開いた場合とバックグラウンドの場合の進み方、失敗・保留・容量不足の表示、再実行時の重複回避を確認する。
- 完了表示だけを原本保存の証明とせず、代表ファイルの取得とハッシュ比較または同等の検証を行う。

### 3. 既存データとの重複と切り替え

- `photo-copy` で取り込み済みのiPhoneデータと、Immichが再アップロードするデータの重複判定を小規模データで確認する。
- External Library内の既存ファイルがモバイルバックアップの重複判定対象にならない場合は、既存分をアップロード対象から外す方法、重複を一時的に許容する方法、または移行する方法を比較して決める。
- 切り替え前のiPhoneおよびMac上のコピーは、主HDD・第2 HDD・必要なAmazon Photosへの保存を確認するまで削除しない。
- 問題がある場合にイメージキャプチャと `photo-copy` の経路へ戻せるよう、切り替え中は既存経路を削除しない。

### 4. フォルダとファイルの扱い

- ImmichのStorage Templateで年月・機器を識別しやすくできるか確認する。
- 現在の `YYYY/YYYY-MM/smartphone/` と日時プレフィックスを完全再現することは必須にせず、Immich管理領域内ではImmichが保証する配置を優先する。
- ファイル単体での復旧可能性と、DBを含む完全復旧の両方を確認する。
- Immich管理領域は通常のファイルとして第2 HDDへ保存するが、日常の整理や削除はImmichのUI/APIを通して行う。

### 5. バックアップ

- 第2 HDDの対象へ、Immich Upload Libraryの原本、アップロード中ファイル、プロフィール、DBダンプ、Compose・設定のうち復元に必要なものを追加する。
- Amazon Photos Desktopの対象へImmich管理領域の静止画を追加し、HEIC・JPEGが保存され、MOVが対象外となることを実機確認する。
- Amazon Photosの対象追加により、サムネイルや変換済み動画などの派生データを誤ってアップロードしない構成にする。
- 主HDD故障、SSD故障、Immich DB喪失の各ケースについて、原本と閲覧環境の復元手順を確認する。

### 6. 正本・手順・スクリプト

- [requirements.md](../../requirements.md) のiPhone取り込み要件を変更する。
- [proposal.md](../../proposal.md) のコピー経路、日常運用、Immich、Amazon Photos、バックアップ、リスクを変更後の構成へ合わせる。
- [setup/](../../setup/) のMac・Ubuntu手順へ、モバイルバックアップ設定、保存場所、切り替え、復旧方法を反映する。
- [scripts/](../../../scripts/) のImmich構築・検査とバックアップスクリプトへ、HDD上の保存場所、マウント検査、必要なバックアップ対象を反映する。
- ホスト固有のパスは `scripts/hosts/*.env` に置き、スクリプトへ直書きしない。

## 対象外

- Sonyカメラの取り込み経路の変更
- ImmichからExternal Libraryの原本を編集・削除できるようにすること
- インターネットからImmichへ接続するための外部公開
- iPhone上での選別、アルバム整理、削除をHDDへ完全同期すること
- Immichを第2 HDDやAmazon Photosに代わる唯一のバックアップとすること

## 完了条件

- [ ] iPhoneからImmichを経由して、代表的なHEIC、JPEG、MOV、Live Photoが主HDDへ保存される。
- [ ] 通常時のiPhone取り込みに、イメージキャプチャ、Macの作業フォルダ、`photo-copy` を必要としない。
- [ ] 初回全件、差分、再実行、通信中断、容量不足、主HDD未マウントを確認し、失敗を成功として扱わない。
- [ ] 既存のiPhoneデータとの重複方針と切り替え手順が決まっている。
- [ ] 主HDD上の原本をImmich外から変更せずに運用できる。
- [ ] 第2 HDDから原本とImmich DB・設定を復元し、Immichで再表示できる。
- [ ] Amazon PhotosへiPhoneの静止画が保存され、動画とImmich派生データが対象外である。
- [ ] `docs/requirements.md`、`docs/proposal.md`、`docs/setup/`、`scripts/` が実機で確認した構成と一致する。
- [ ] Markdownと変更したスクリプトの検査に合格する。
