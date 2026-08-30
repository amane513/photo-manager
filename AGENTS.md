# プロジェクト共通の作業指示

CodexとClaude Codeが共有する指示をこのファイルに記載する。

## プロジェクト概要

写真・動画管理環境（Sony α7C II、iPhone 13、MacBook Air、Ubuntu常時稼働PC + Immich、4TB HDD、Amazon Photos）の
要件・構成・変更計画を管理するドキュメントリポジトリ。現時点でアプリケーションコードは含まない。

- [docs/requirements.md](docs/requirements.md): 実現したいことと前提条件（正本）
- [docs/proposal.md](docs/proposal.md): 現在採用している構成と運用の提案（正本）
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

- `NNNN` は作成順の4桁連番とし、一度採番した番号は変更・再利用しない。
- 説明部分は英小文字のkebab-caseとする。
- 完了・保留などの状態はフォルダ名に含めず、`plan.md` に記録する。
- 完了したプランも削除せずに残す。
- 一覧は [docs/plans/roadmap.md](docs/plans/roadmap.md) に反映する。

詳細は [docs/plans/README.md](docs/plans/README.md) を参照する。

## 設定の保守

- 共通の指示は `CLAUDE.md` ではなくこのファイルを更新する。
- `CLAUDE.md` は `AGENTS.md` を読み込む薄いアダプタとし、Claude Code固有の指示だけを記載する。
- ツール横断で再利用するワークフローは `.agents/skills/` に置く。

## Git運用

- ユーザーから明示的な指示がない限り、このリポジトリのコミットは `main` ブランチ上で実施する。
