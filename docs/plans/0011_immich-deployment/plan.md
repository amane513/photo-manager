# 0011: Immichの導入とCUDA機械学習の構築

作成日: 2026-09-13

更新日: 2026-09-13

状態: 設計済み・未着手

## 目的

Ubuntu常時稼働PCの内蔵SSDへImmichを再構築可能な形で導入し、主HDDの正本を読み取り専用のExternal Libraryとして登録する。家庭内LANからタイムラインを閲覧でき、Immichの障害や操作が原本を変更しない構成にする。

RTX 4060 Ti 16GBを初期導入から機械学習に使用する。Smart Searchには、Immich公式の現行比較で日本語検索の評価が最も高い `XLM-Roberta-Large-ViT-H-14__frozen_laion5b_s13b_b90k` を採用し、既定の英語中心モデルでは索引を作らない。CPU構成でサービス自体の最小スモークテストを行った後、全ライブラリの索引作成前にCUDA構成へ切り替える。

また、Immichが実際に生成したPostgreSQLダンプを内蔵SSD上に残し、0012の復元試験と0013の第2 HDDバックアップへ引き継ぐ。

## 背景

- 0010で、SDカードの保存対象1,005件・28,746,500,376バイトが主HDDへ正しく取り込まれたことをSHA-256まで確認した。0011はこのライブラリを変更せず閲覧対象にする。
- 正本は `/mnt/camera_archive/photo-library/` にあり、Immichは保管場所ではなく閲覧・検索用の派生システムである。
- Ubuntu PCにはRTX 4060 Ti 16GBがある。Immichの現行公式要件ではCUDAにcompute capability 5.2以上、NVIDIAドライバー545以上、LinuxではNVIDIA Container Toolkitが必要である。
- Immich公式の現行モデル比較では、指定するXLM-Rモデルの日本語Recallは83.95%、推定メモリ使用量は4,014 MiBであり、日本語表の先頭かつPareto最適である。16GB VRAMのGPUで初期候補にする合理性がある。ただし公式値はCPU・FP32で得た比較値であり、この実機の処理時間やVRAM使用量を保証する値ではない。
- 現在の提案とロードマップは、0011をCPU導入、0018をGPU高速化として分けている。既定モデルで全件索引を作った後にモデルを替えるとSmart Searchの再処理が必要になるため、機械学習のCUDA化とモデル選択を0011へ前倒しする方が無駄が少ない。
- Immich v3系は、DBダンプを `UPLOAD_LOCATION/backups` に自動生成し、管理画面から手動生成もできる。0011では製品の標準機能で実ダンプを生成し、独自の定期ダンプ処理は追加しない。

## 設計上の決定

### 1. 0011にCUDA機械学習を含める

0011の完了状態は、CPUだけで起動できる状態ではなく、`immich-machine-learning` がRTX 4060 TiをCUDA経由で使用できる状態とする。

導入順は次のとおりとする。

```text
ホストとSSDの事前検査
  ↓
Docker ComposeによるCPU構成の起動
  ↓
DB・Redis・Web・機械学習サービスの最小スモークテスト
  ↓
NVIDIAドライバーとContainer Toolkitの確認・導入
  ↓
CUDA版機械学習コンテナへ切替
  ↓
XLM-Rモデルを設定・取得
  ↓
External Libraryをread-onlyで登録
  ↓
全件スキャンとSmart Search索引作成
```

CPU確認はサービス、DB、ストレージ配置の問題とGPUランタイムの問題を切り分けるための一時的な段階である。CPU既定モデルによるSmart Search全件ジョブは実行しない。CUDA切替後も同じDBとモデルキャッシュを使うため、構成を戻しても原本やImmichの管理情報を作り直さない。

動画トランスコードのGPU高速化は0011へ含めず、0018に残す。これにより、閲覧に必要な初期導入と日本語検索は今回完成させつつ、動画コーデック、品質、デバイス指定の判断を混在させない。0018には、実運用後に必要となった機械学習モデルや常駐設定の再調整も残す。

### 2. Smart SearchモデルをXLM-R Largeに固定する

初期モデルは次に固定する。

```text
XLM-Roberta-Large-ViT-H-14__frozen_laion5b_s13b_b90k
```

このモデルは日本語と英語を混在させても言語指定トークンを必要としない。日本語だけならNLLB系も候補になるが、現行のImmich公式比較では日本語RecallがXLM-R Largeを下回り、検索時の言語設定にも依存するため初期候補にしない。SigLIP2系も現行の日本語評価では指定モデルを下回る。

モデル名は管理画面の `Administration > Settings > Machine Learning Settings > Smart Search` に設定し、DBへ保存する。モデル設定後にSmart Searchの全件ジョブを1回だけ開始する。モデルキャッシュは内蔵SSDの `/srv/immich/model-cache/` へ永続化し、コンテナ更新で再取得しない。

顔認識とOCRはImmichの既定モデルを使う。Smart Search以外のモデル変更を同時に行わず、GPU利用の成否と日本語検索の評価対象を明確にする。

`MACHINE_LEARNING_WORKERS` は1、GPU device IDは0から始める。ワーカーを増やすとモデルごとにメモリが複製されるため、16GB VRAMがあっても初期値では増やさない。モデルのTTL、事前ロード、ジョブ並列数も既定値から始め、初回検索の待ち時間やVRAM競合が実害になった場合だけ0018または後続の小変更で調整する。

### 3. Immichは安定版を完全なバージョン番号で固定する

設計時点の最新安定版はv3.2.0である。実装開始時に公式リリースとリリースノートを再確認し、その時点の最新安定版を採用する。RC版は採用しない。採用後は `v3` や `release` のような可変タグではなく、`vX.Y.Z` の完全なバージョン番号をリポジトリ管理の設定へ記録する。

Immichは古いパッチ版への修正のバックポートとダウングレードを前提にしていないため、「永続的に古い版へ固定」するのではなく、「意図せず更新されないよう固定し、更新はDBダンプとリリースノート確認を伴う明示操作にする」という意味である。0011では導入と同時に一般化した自動更新機構を作らない。

Compose定義は採用したImmichリリースの公式 `docker-compose.yml` と `hwaccel.ml.yml` を基準に、次のローカル差分だけを持つ。

- `/srv/immich/` 以下のSSD配置
- 主HDDのread-onlyマウント
- 家庭内LAN用の待受アドレス
- CUDA版機械学習サービス
- 永続化するモデルキャッシュ

### 4. SSD上の配置を1つのルートにまとめる

ホスト側は次の配置にする。

```text
/srv/immich/
├── app/                 # Compose定義と秘密値を含む実行時.env
├── data/                # UPLOAD_LOCATION
│   ├── backups/         # Immichが生成するDBダンプ
│   ├── encoded-video/
│   ├── library/
│   ├── profile/
│   ├── thumbs/
│   └── upload/
├── postgres/            # DB_DATA_LOCATION
└── model-cache/         # 機械学習モデル
```

公式構成に合わせて `UPLOAD_LOCATION=/srv/immich/data` を1つのbind mountにし、同じSSD上の各サブディレクトリを個別マウントしない。PostgreSQLとモデルキャッシュだけを分離する。原本はここへアップロードせず、主HDD上のExternal Libraryを使う。

`/srv/immich/app/.env` にはDBパスワードが入るためコミットせず、所有者root・モード0600とする。セットアップの通常実行時に秘密値を対話入力し、既存の `.env` を無断で置換しない。ホスト固有だが秘密でない値は `scripts/hosts/*.env` に置く。

### 5. Composeと実機設定をスクリプトから再構築できるようにする

リポジトリに次を追加する。実装時にファイル名を変える場合も責務は維持する。

```text
scripts/ubuntu/immich/
├── docker-compose.yml
├── compose.ml-cuda.yml
├── hwaccel.ml.yml
└── immich.env.example
scripts/ubuntu/inspect-immich-host.sh
scripts/ubuntu/setup-immich-runtime.sh
scripts/ubuntu/setup-immich.sh
scripts/ubuntu/verify-immich.sh
```

- `inspect-immich-host.sh`: OS、CPUアーキテクチャ、RAM、SSDのファイルシステム・空き容量、Docker、Compose、GPU、ドライバー、Container Toolkit、主HDDマウントを読み取り専用で報告する。
- `setup-immich-runtime.sh`: Docker Engine、Compose plugin、NVIDIA Container Toolkitの不足分だけを公式リポジトリから導入する。`--dry-run` を備え、既存の競合パッケージや未確認のDocker構成がある場合は停止する。ドライバー変更やSecure Boot対応で再起動が必要な場合は成功扱いせず、再起動後の再実行を案内する。
- `setup-immich.sh`: `/srv/immich/` の作成、Compose定義の配置、秘密値の初期設定、CPU起動、CUDA切替、再実行を扱う。`--dry-run` を備え、実行中の異なるComposeや既存データを無断で採用・上書きしない。
- `verify-immich.sh`: サービスのhealth、固定バージョン、SSD配置、LAN待受、主HDDのread-onlyマウント、CUDA provider、GPU割当、モデルキャッシュ、DBダンプを読み取り専用で検査する。

CPU構成を基底の `docker-compose.yml`、CUDA差分を `compose.ml-cuda.yml` として分ける。通常運用のコマンドは両方を明示するラッパーまたはスクリプトへ統一し、利用者が誤ってCPU構成だけで再作成しないようにする。CPUへのロールバックは基底Composeを使えば可能だが、通常手順にはしない。

リポジトリ管理のComposeと `/srv/immich/app/` の実体が異なる場合、セットアップは差分を表示して停止する。更新すると明示した場合だけ、既存ファイルを日時付きで退避して置き換える。DBディレクトリ、`data/`、モデルキャッシュは設定更新の対象にしない。

### 6. External Libraryはコンテナ境界でもread-onlyにする

ホストのライブラリルートを次の固定パスでマウントする。

```yaml
volumes:
  - /mnt/camera_archive/photo-library:/external/photo-library:ro
```

実際のComposeではホスト設定から解決してもよいが、コンテナ内パスは `/external/photo-library` に固定する。External Libraryのimport pathもこのコンテナ内パスを指定する。

登録前に次を確認する。

- `ARCHIVE_LIBRARY_ROOT` が期待する主HDD UUID上にある。
- シンボリックリンクではない。
- コンテナから一覧と代表ファイルを読み取れる。
- コンテナからファイルを作成・更新・削除できない。
- 主HDDが未マウントならImmichを起動または再作成しない。

ライブラリ名は `photo-library`、所有者は初期管理ユーザーとする。所有者は後から変更できないため、管理ユーザー作成後に手動で登録する。

除外パターンはスキャン前に次を設定する。

```text
**/*.ARW
**/*.arw
```

0011では設定が保存されたこととスキャンジョブが完了したことまで確認する。ARWが表示されないこと、JPEG・HEIC・Live Photo・動画・現像済みJPEGの表示内容、途中ファイルの扱いは0012でメディア単位に検証する。

### 7. 家庭内LANだけで待ち受ける

Immichのポート2283は、ホストのLAN側固定アドレスにbindし、`0.0.0.0` へ無条件に公開しない。LANアドレスはホスト設定へ追加する。ルーターのポート転送、UPnPによる公開、Tailscale、リバースプロキシ、公開DNS、外部TLS終端は0011の対象外とする。

初期管理ユーザーの作成とパスワード設定はWeb UIで手動実施し、秘密情報をリポジトリや検証記録へ残さない。iPhoneアプリからの自動アップロードも有効にしない。

### 8. DBダンプはImmich標準機能で生成する

External Libraryとモデル設定をDBへ保存した後、管理画面のJob Queuesから `Create Database Dump` を1回実行する。生成された `.sql.gz` が `/srv/immich/data/backups/` にあり、0バイトでなく、gzip検査に通り、実行中のImmichバージョンを識別できることを `verify-immich.sh` で確認する。

自動DBバックアップは既定の日次2:00・14世代から開始する。保持数や時刻は実運用後に変更できるが、0011では独自cronを重ねない。このダンプはまだ同じSSD上にしかないためバックアップ完了ではない。0012で復元し、0013で第2 HDDへコピーして初めて別媒体に保全される。

## 対象範囲

- UbuntuホストとSSD容量の事前検査
- Docker EngineとDocker Compose pluginの再構築手順
- NVIDIAドライバー545以上とNVIDIA Container Toolkitの確認・不足時導入
- 完全なImmich安定版番号を固定したDocker Compose構成
- 内蔵SSD `/srv/immich/` へのDB、派生データ、モデルの配置
- CPU構成による最小スモークテストとCUDA機械学習への切替
- XLM-R Largeモデルの設定、取得、CUDA利用、Smart Search全件ジョブ
- 主HDDのread-onlyマウントとExternal Library登録
- ARW除外パターンの設定
- 家庭内LANからのWebアクセス
- Immich標準機能による実DBダンプの生成
- `docs/setup/ubuntu.md`、`docs/setup/README.md`、`scripts/`、ホスト設定、提案書への反映

## 範囲外

- 動画トランスコードのGPU高速化（0018）
- XLM-R Large以外のモデルとの網羅的な品質・速度比較
- 顔認識モデル、OCRモデル、閾値、ジョブ並列数のチューニング
- モデルを常時VRAMへ保持するためのTTL・preload調整
- ARW除外や各メディアの表示品質、Live Photoの組、途中ファイルの実挙動の合否判定（0012）
- DB復元（0012）
- 第2 HDDへのDB・設定・原本のバックアップ（0013）
- インターネット公開、VPN、リバースプロキシ、公開TLS
- iPhoneアプリからの自動アップロード
- 祖父母向け共有方法の変更（0019）
- Immichからの原本削除、XMP書込み、ファイル移動・改名
- 自動更新と無人アップグレード

## 実施手順

結果は `validation.md` に記録する。秘密値、アクセストークン、写真の内容が分かるスクリーンショットは記録しない。

### 段階1: ホストと既存状態を調査する

- [ ] `inspect-immich-host.sh` を実装し、実機でOS・アーキテクチャ・RAM・SSD容量とファイルシステムを記録する。
- [ ] `nvidia-smi` でRTX 4060 Ti 16GB、GPU device 0、ドライバーバージョンを確認する。
- [ ] Docker Engine、`docker compose`、NVIDIA Container Toolkit、既存コンテナ・ネットワーク・Compose構成の有無を確認する。
- [ ] `/srv/immich/` の既存データを確認する。既存のImmichまたはPostgreSQLデータがあれば新規導入として上書きせず、移行プランが必要か判断する。
- [ ] `/srv` の空き容量を記録する。原本27GBとは別に、公式目安でサムネイルと変換動画がライブラリの10〜20%程度増えること、DB、コンテナイメージ、約4GB級モデルと更新時の一時的な重複を見込み、不足なら開始しない。
- [ ] 主HDDのUUID、マウント、`ARCHIVE_LIBRARY_ROOT`、所有者・権限が0005・0008の検証結果と一致することを確認する。

### 段階2: バージョンと配布物を固定する

- [ ] 実装日時点の最新安定版とリリースノートを公式GitHub Releasesで確認し、RCでないことを確認する。
- [ ] 公式リリースの `docker-compose.yml`、`example.env`、`hwaccel.ml.yml` を取得し、取得元URL、バージョン、SHA-256を記録する。
- [ ] 必要最小限のローカル差分を `scripts/ubuntu/immich/` に実装し、`IMMICH_VERSION` を完全なバージョン番号に固定する。
- [ ] Composeの解決結果を検査し、可変タグ、ホスト上の意図しないパス、公開範囲の広いポート、主HDDの書込み可能マウントがないことを確認する。

### 段階3: コンテナランタイムを構築する

- [ ] `setup-immich-runtime.sh` にdry-run、通常実行、再実行時の保護を実装する。
- [ ] dry-runで追加・変更されるaptリポジトリ、鍵、パッケージ、Docker設定を確認する。
- [ ] Docker公式手順に基づくEngineとCompose pluginを、不足する場合だけ導入する。
- [ ] NVIDIA公式手順に基づくドライバー545以上とContainer Toolkitを、不足する場合だけ導入・設定する。
- [ ] 再起動が必要な場合は再起動前に段階を完了扱いせず、再起動後に `nvidia-smi` とGPUを要求するテストコンテナで利用可能性を再確認する。
- [ ] Secure Bootや既存Docker設定により自動化できない操作があれば、推測で変更せず `docs/setup/ubuntu.md` に実機どおりの手動手順を残す。

### 段階4: SSD配置と秘密値を構築する

- [ ] ホスト設定へImmichのルート、LAN bind address、ポート、固定バージョンなど秘密でない値を追加する。
- [ ] `setup-immich.sh --dry-run` で作成先、所有者、権限、Compose差分を表示する。
- [ ] 通常実行で `/srv/immich/{app,data,postgres,model-cache}` を作成する。既存の非空ディレクトリは無断で採用しない。
- [ ] DBパスワードを対話入力して `/srv/immich/app/.env` をroot所有・0600で作成する。dry-run、標準出力、ログ、Git管理ファイルへ秘密値を出さない。
- [ ] 同じスクリプトを再実行し、既存の秘密値、DB、派生データ、モデルを変更せず冪等に終了することを確認する。

### 段階5: CPU構成で最小起動を確認する

- [ ] 基底Composeだけでサービスを起動し、PostgreSQL、Redis、Immich server、machine learningのhealthを確認する。
- [ ] PostgreSQLが `/srv/immich/postgres/`、Immichデータが `/srv/immich/data/`、モデルが `/srv/immich/model-cache/` に対応するmountを使用することを確認する。
- [ ] LAN上のMacから `http://<LANアドレス>:2283` を開けること、LAN bind以外へ公開していないことを確認する。
- [ ] CPU構成では管理ユーザー作成、External Library登録、Smart Search全件ジョブをまだ行わない。

### 段階6: CUDA機械学習へ切り替える

- [ ] CUDA overrideを含む通常運用構成でmachine learningサービスを再作成する。
- [ ] Composeの解決結果とコンテナ情報でGPU device 0が割り当てられていることを確認する。
- [ ] machine learningログの `Available ORT providers` に `CUDAExecutionProvider` があり、CPUだけへ黙ってフォールバックしていないことを確認する。
- [ ] `nvidia-smi` でコンテナのプロセスとVRAM使用を確認する。
- [ ] CPU構成へ戻す操作とCUDA構成へ再度進める操作を手順化する。DB・data・モデルキャッシュを削除しないことを確認する。

### 段階7: 初期設定とExternal Libraryを登録する

- [ ] Web UIで初期管理ユーザーを作る。認証情報は記録しない。
- [ ] Smart Searchモデル名をXLM-R Largeへ変更し、保存する。既定モデルの全件ジョブは開始しない。
- [ ] External Library `photo-library` を初期管理ユーザー所有で作り、import path `/external/photo-library` を追加する。
- [ ] 最初のスキャン前にARWの大文字・小文字2パターンを除外設定へ追加する。
- [ ] コンテナ内でExternal Libraryを読み取れる一方、書込みできないことを検証する。検証のために原本へ一時ファイルを作らない。
- [ ] 全ライブラリのスキャンを開始し、Library、metadata、thumbnail等のジョブが失敗なく完了することを確認する。
- [ ] XLM-R Largeを使うSmart Search全件ジョブを開始し、完了件数とエラー件数を記録する。

### 段階8: GPUと日本語検索を実機確認する

- [ ] モデルキャッシュにXLM-R Largeが取得され、再起動後も再ダウンロードされないことを確認する。
- [ ] Smart Searchジョブ中に `CUDAExecutionProvider` とRTX 4060 Tiの利用を確認し、ピークVRAM、所要時間、失敗件数を記録する。
- [ ] 実データに存在すると分かっている対象について、日本語の具体的な検索語を5件以上、英語または日英混在を2件以上試す。
- [ ] 各検索について、期待する写真が上位20件に含まれるかと、結果が実用的かを利用者が確認し、検索語と合否だけを `validation.md` に記録する。写真の内容や人物名は必要以上に記録しない。
- [ ] 検索品質に不足があっても、モデルが正しく設定されCUDAで全件処理できていれば0011の構築失敗とはしない。モデル比較が必要なら、候補、再索引コスト、評価語を整理して別の判断にする。

### 段階9: DBダンプを生成する

- [ ] 管理画面から `Create Database Dump` を実行する。
- [ ] `/srv/immich/data/backups/` に実ダンプが生成され、0バイトでなくgzip検査に通ることを確認する。
- [ ] ダンプのファイル名、サイズ、SHA-256、生成したImmichバージョンを `validation.md` に記録する。
- [ ] 自動バックアップが日次2:00・14世代で有効であることを確認する。
- [ ] ダンプは同じSSD上にしかなく、0012の復元確認前かつ0013の別媒体保存前であることを明記する。

### 段階10: 再構築手順と正本を更新する

- [ ] `docs/setup/ubuntu.md` に事前検査、ランタイム導入、dry-run、CPUスモークテスト、CUDA切替、初期UI設定、External Library、モデル設定、DBダンプ、通常起動・停止・更新・ロールバックを記載する。
- [ ] `docs/setup/README.md` のImmich導入を整備済みに更新する。
- [ ] `docs/proposal.md` のSSD配置、Immich段階導入、GPUのプラン境界を実装結果へ合わせる。
- [ ] `scripts/hosts/ubuntu.env.example` と実機用ホスト設定へ秘密でない値を反映する。
- [ ] セットアップスクリプトと確認スクリプトを実機で実行し、未実行のスクリプトを完成扱いにしない。
- [ ] `git diff --check` と既存のコピーCLIテストを実行し、0011が取り込み環境を壊していないことを確認する。
- [ ] 0012へ代表メディア、External Library設定、DBダンプ、固定バージョンを引き継ぐ。
- [ ] 0013完了まではSDカードを含むコピー元を削除しないことを再確認する。

## 検証項目

| ID | 区分 | 確認すること | 完了基準 |
|---|---|---|---|
| I01 | 事前条件 | SSD、主HDD、OS、RAM、GPU、既存Docker状態を読み取り専用で調査できる | 実機値と競合の有無を記録した |
| I02 | 再構築 | Docker・Compose・NVIDIA runtimeをdry-run付きスクリプトで再現できる | 不足分だけ導入し、再実行に成功した |
| I03 | バージョン | RCや可変タグでなく完全な安定版番号を使う | 実行中コンテナと記録した版が一致する |
| I04 | 配置 | DB、data、モデルが内蔵SSDの所定パスにある | mountと実ファイルを検査できる |
| I05 | 秘密 | DBパスワードをコミット・出力・無断置換しない | `.env` がroot所有・0600で、Git管理外である |
| I06 | 基本起動 | CPU構成で全サービスがhealthになる | External Library登録前のスモークテストが成功する |
| I07 | CUDA | machine learningがRTX 4060 Tiを使用する | `CUDAExecutionProvider`、GPU割当、`nvidia-smi`の3点で確認する |
| I08 | モデル | XLM-R Largeで全アセットのSmart Search索引を作る | モデル名、ジョブ完了、キャッシュ永続化を確認する |
| I09 | 日本語検索 | 日本語検索が実データに対して利用できる | 5件以上の日本語検索結果を利用者が評価した |
| I10 | 原本保護 | 主HDDをコンテナへread-onlyで提供する | コンテナから読めるが書けず、原本を変更していない |
| I11 | LAN限定 | 家庭内LANから閲覧でき、意図しない全IF公開をしない | bind addressとMacからの接続を確認した |
| I12 | External Library | `photo-library` を登録しARW除外を保存する | import pathと除外2パターンがDBに保存された |
| I13 | DBダンプ | Immichの実DBダンプを生成する | `.sql.gz` のgzip検査、サイズ、SHA-256を記録した |
| I14 | 保護 | 既存データ・設定を無断で上書きしない | dry-run、競合時停止、再実行を確認した |
| I15 | 正本 | setup、scripts、proposal、roadmapが実機構成と一致する | 新しいPCで必要な自動・手動手順を辿れる |

## 完了条件

- Immichの固定した安定版がDocker Composeで起動し、全サービスが正常である。
- PostgreSQL、Immich data、モデルキャッシュが内蔵SSDの `/srv/immich/` 以下へ置かれている。
- RTX 4060 Tiがmachine learningコンテナへ割り当てられ、`CUDAExecutionProvider` と実際のGPU利用を確認している。
- Smart SearchがXLM-R Largeモデルを使用し、全件ジョブが完了している。既定モデルで先に全件索引を作っていない。
- 5件以上の日本語検索と2件以上の日英混在または英語検索を実データで評価し、結果を記録している。
- 主HDDの `/mnt/camera_archive/photo-library/` が `/external/photo-library` へread-onlyでマウントされ、Immichから原本を変更できない。
- External LibraryとARW除外パターンが登録されている。形式別の表示合否は0012へ明確に引き継いでいる。
- 家庭内LANから閲覧でき、外部公開、モバイル自動アップロード、動画GPU変換を有効にしていない。
- Immichが生成した実DBダンプが内蔵SSD上にあり、gzip検査、サイズ、SHA-256、生成バージョンを記録している。
- 導入・検査スクリプトがdry-run、冪等性、競合時停止を備え、実機で確認されている。
- `docs/setup/ubuntu.md` と `scripts/` だけで同じ構成を再構築するための自動・手動手順が揃っている。
- 0013完了まではコピー元を削除していない。

## 失敗時の扱いとロールバック

- CPUスモークテストに失敗した場合はGPU構成へ進まず、サービス、DB、権限、SSD配置を修正する。
- CUDAで失敗した場合は、DB・data・モデルキャッシュを保持したまま基底ComposeのCPU構成へ戻せるようにする。ただし0011はGPU利用を完了条件とするため、CPUで動いたことだけでは完了扱いにしない。
- モデル取得またはロードに失敗した場合は、ログと不完全なキャッシュの状態を記録する。キャッシュを削除する必要がある場合は対象モデルのディレクトリを完全パスで特定し、原本・DB・他モデルを対象にしない。
- External Libraryの書込み可能性が見つかった場合はスキャンを開始せず、Composeのmountを修正して再作成する。
- 既存の `/srv/immich/` やDocker構成と競合した場合は自動採用・削除せず停止する。
- DBダンプが生成・検査できない場合は0012へ進まない。

## 0012・0013・0018への引継ぎ

- **0012**: 同じ固定バージョンと実DBダンプを使い、ARW除外、JPEG・HEIC・Live Photo・動画・現像済みJPEG、途中ファイル、DB復元を確認する。復元試験ではExternal Libraryの同一コンテナパスを維持する。
- **0013**: `/srv/immich/data/` のうち復元に必要な内容、DBダンプ、Composeの公開設定、秘密値を含む実行時設定の安全な保全方法を決める。model-cache、thumbs、encoded-videoは再生成可能として、容量と復旧時間を踏まえて対象を判断する。
- **0018**: 動画トランスコードのGPU高速化を主対象とする。機械学習については、0011の実測後に必要な場合だけモデル比較、TTL、preload、並列数を調整する。

## 設計時に参照した公式資料

- [Immich: Docker Compose](https://docs.immich.app/install/docker-compose/)
- [Immich: Requirements](https://docs.immich.app/install/requirements/)
- [Immich: Hardware-Accelerated Machine Learning](https://docs.immich.app/features/ml-hardware-acceleration/)
- [Immich: Searching and multilingual model comparison](https://docs.immich.app/features/searching/)
- [Immich: External Libraries](https://docs.immich.app/features/libraries/)
- [Immich: Backup and Restore](https://docs.immich.app/administration/backup-and-restore/)
- [Immich: Environment Variables](https://docs.immich.app/install/environment-variables/)
- [Immich: Releases](https://github.com/immich-app/immich/releases)
