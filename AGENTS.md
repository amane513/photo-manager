# プロジェクト共通の作業指示

CodexとClaude Codeが共有する指示をこのファイルに記載する。

## プロジェクト概要

写真・動画管理環境（Sony α7C II、iPhone 13、MacBook Air、Ubuntu常時稼働PC + Immich、4TB HDD、Amazon Photos）の
要件・構成・変更計画を管理するリポジトリ。環境構築スクリプトに加え、写真・動画を配置するコピーCLIの実装を含む。

- [docs/requirements.md](docs/requirements.md): 実現したいことと前提条件（正本）
- [docs/proposal.md](docs/proposal.md): 現在採用している構成と運用の提案（正本）
- [docs/setup/](docs/setup/): 新しいPCで環境を再構築するための手順（正本）
- [scripts/](scripts/): 環境構築を自動化するスクリプト
- [src/photo_copy/](src/photo_copy/): コピーCLI `photo-copy` の実装
- [tests/](tests/): コピーCLIの自動テスト
- [docs/plans/](docs/plans/): 変更単位の目的・範囲・手順・完了条件
- [docs/archive/](docs/archive/): 現在の正本ではない検討案や過去の資料

方針を判断するときは、必ず `docs/requirements.md` と `docs/proposal.md` を参照する。
`docs/archive/` は経緯確認のための資料であり、現在の方針の根拠として扱わない。

## ドキュメントの扱い

- 記述は日本語、常体（である調）で統一する。
- 要件を変更した場合は、提案との整合も確認する。
- 実装方法だけを変更する場合は、要件を変更せず、提案または変更プランへ反映する。
- 詳しい運用ルールは [docs/README.md](docs/README.md) を参照する。

## 変更プラン

リポジトリへの変更は、`docs/plans/NNNN_short-description/plan.md` に記録する。

- `NNNN` は0001からの4桁連番とし、推奨する着手順を表す。欠番は作らない。
- 推奨順が変わった場合はロードマップ全体を再採番し、フォルダ名と参照も合わせて更新する。
- 説明部分は英小文字のkebab-caseとする。
- 完了・保留などの状態はフォルダ名に含めず、`plan.md` に記録する。
- 完了したプランも削除せずに残す。
- 一覧は [docs/plans/roadmap.md](docs/plans/roadmap.md) に反映する。

詳細は [docs/plans/README.md](docs/plans/README.md) を参照する。

## 再構築性

新しいPCで同じ環境を組み直せる状態を保つ。手順の正本は `docs/setup/`、実体は `scripts/` に置く。

- 環境を変更するプランは、`docs/setup/` と `scripts/` の更新までを成果物に含める。
- 作業後に手順を清書するのではなく、作業時にスクリプトを書いて実行する。実機で動かしていないスクリプトを完成として扱わない。
- スクリプトは冪等とし、dry-runを備え、既存の設定やデータを無断で上書きしない。失敗を成功として扱わない。
- 完了条件は可能な限り確認用スクリプトにし、再構築先で同じ状態になったことを判定できるようにする。
- 物理作業やGUIアプリの操作など自動化できない部分は、`docs/setup/` に手動手順として明記する。
- ホスト固有の値は `scripts/hosts/*.env` に分離し、スクリプトへ直書きしない。パスワード等の秘密情報はコミットせず実行時に入力する。
- `plan.md` と `validation.md` は当時の記録であり、再構築の手順としては使わない。

詳細は [docs/setup/README.md](docs/setup/README.md) を参照する。

## アプリケーションコード

コピーCLI `photo-copy` を `src/photo_copy/` に置く。0006で構築中であり、利用手順の正本は [docs/setup/mac.md](docs/setup/mac.md) である。

- 実行環境はプロジェクト専用の `.venv/`（Python 3.10以上）とする。導入は `scripts/mac/setup-copy-cli.sh`、検査は `scripts/mac/verify-copy-cli.sh` で行う。
- 自動テストは `.venv/bin/python -m unittest discover -s tests` で実行する。標準ライブラリの unittest だけを使い、テスト用の依存を増やさない。
- CLI層は引数処理と表示だけを担い、判断と実行は共通処理APIに置く。0014でGUIから同じAPIを使える形を保つ。
- ExifTool、rsync、sshなどの外部コマンドは呼び出し可能オブジェクトとして注入し、テストで差し替えられるようにする。実機の接続先や実データに依存する自動テストを書かない。
- テストは一時ディレクトリだけを使い、既存の写真ライブラリや主HDD上のデータを変更しない。
- コメントとdocstringも日本語・常体とする。

## 設定の保守

- 共通の指示は `CLAUDE.md` ではなくこのファイルを更新する。
- `CLAUDE.md` は `AGENTS.md` を読み込む薄いアダプタとし、Claude Code固有の指示だけを記載する。
- ツール横断で再利用するワークフローは `.agents/skills/` に置く。

## Git運用

- ユーザーから明示的な指示がない限り、このリポジトリのコミットは `main` ブランチ上で実施する。

## Ubuntuへの接続とリモート作業

- UbuntuへSSH接続するときは、まず `ssh ubuntu` を試す。接続できない場合は `ssh ubuntu_by_tailscale` を試す。
- Ubuntu上の `~/work/photo-manager` は実機への反映・検証に使うcheckoutとし、ソースやドキュメントを直接編集しない。変更はMac側のこのリポジトリで行い、`main`へコミットしてoriginへpushした後、Ubuntu側で `git pull --ff-only origin main` により反映する。
- Ubuntu上のリポジトリへ `scp`、`rsync`、パイプ経由の `git apply` などで未コミットのファイルを配置しない。実機で得た検証結果もMac側で `validation.md` 等へ記録し、コミット経由で反映する。
- Ubuntuで作業を始める前と終えた後に `git status --porcelain` を確認する。差分がある場合は、別セッションの作業である可能性があるため、stash、reset、上書き、削除を行わず、内容と状況をユーザーへ報告して停止する。
- Ubuntu側のmainを更新する前に作業ツリーがcleanであることを確認する。更新にはfast-forwardのみを許可し、追従後は `git rev-list --left-right --count main...origin/main` が `0 0` であることを確認する。
