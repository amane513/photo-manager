# 0010 検証記録

実施日: 2026-09-13

## 隔離した自動検証

一時ディレクトリだけを使用して、通常の `copy` が新規コピー後にサイズ・SHA-256を照合し、マニフェストを生成することを確認した。既存一致の再実行では、コピー前に得たハッシュを検証へ再利用することも確認した。

```sh
.venv/bin/python -m unittest discover -s tests
./scripts/mac/verify-copy-cli.sh --project-root .
```

結果: 115 tests passed。実行環境、rsync 3.5.0、ExifTool 13.55、および全件検証APIを確認した。

## 隔離した異常系検証（追記）

実施日: 2026-09-13

```sh
.venv/bin/python -m unittest discover -s tests
./scripts/mac/verify-copy-cli.sh --project-root .
git diff --check
```

結果: 119 tests passed。`ScenarioTransfer` は送信完了後の検証フェーズだけで配置先の状態またはハッシュ応答を変え、`ReadOnlyFake` は `ensure_directories()` または `send()` が呼ばれると即座に失敗する。すべて一時ディレクトリと注入したフェイクだけを使用した。

- `missing`、同サイズの `different`、通常ファイル以外、コピー元・配置先の読取不能を、それぞれ成功扱いにしないことを確認した。
- コピー元のハッシュ計算中の変更と、配置先のハッシュ前後のfactsの変化を、不一致または読取不能として記録した。
- 転送中断はコピー結果の中断と検証未実行、コピー後検証中断はコピー成功済みと検証未完了として区別した。
- 検証APIは読み取り専用の型境界を使用し、書き込み操作を呼ばないことを確認した。
- 異常時も送信回数を増やさず、コピー済み・既存配置先・コピー元を削除または上書きせず、構造化結果とJSONログへ状態を残すことを確認した。
- SDカード、Ubuntu主HDD、実際の写真ライブラリおよび実データは変更していない。

## 実機検証

SDカード `/Volumes/CameraSD` とUbuntu主HDDで、次を実行した。

```sh
.venv/bin/photo-copy check --host-config ./scripts/hosts/ubuntu-amane-yajima.env
.venv/bin/photo-copy copy --profile sd-to-ubuntu
```

接続、主HDDマウント、rsyncの事前検査は成功した。通常実行の結果は次のとおりである。

- コピー: 新規コピー0件、既存一致1,005件、衝突・失敗・未処理0件
- 検証: 一致1,005件、欠損・不一致・読取不能・未解決0件
- 対象外: Sony管理情報10件、macOS補助ファイル7件
- 対象総容量: 28,746,500,376バイト
- `manifest_sha256`: `c496361e21626ab6e0a04f2d722d2fcc6e0ea58e4b26e5d20c3bf21028a25dce`
- 所要時間: コピー前照合179.810秒、コピー後検証0.006秒
- 詳細ログ: `.photo-copy-logs/copy-20260913-103032-579682.json`

全対象が既存一致であったため、新規送信は行われなかった。コピー元と主HDDの実データを削除・変更していない。
