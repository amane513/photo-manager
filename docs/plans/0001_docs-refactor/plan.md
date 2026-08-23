# 0001: docsリファクタ

作成日: 2026-08-23  
状態: 完了

## 目的

- 現在の正本と検討過程の資料を明確に分離する。
- 変更単位の計画を連番フォルダで蓄積できるようにする。
- `requirements.md` を、意味を変えずに継続的に更新しやすい要件文書へ再構成する。

## 対象範囲

- `docs` の索引追加
- `docs/plans` の運用ルール追加
- `0001_docs-refactor` の計画記録
- 比較検討に使用したClaude案とCodex案のアーカイブ移動
- `requirements.md` の見出し、分類、表記の整理

`proposal.md` の内容は変更しない。

## 決定

- `requirements.md` と `proposal.md` は、それぞれ「何を実現したいか」と「どのように実現するか」を表す現在の正本として `docs` 直下に残す。
- 検討案は `docs/archive/proposals/<date>/alternatives/` に保存する。
- プランフォルダは `NNNN_short-description` 形式とし、状態による改名は行わない。
- プランは原則として `plan.md` 一つで始め、必要になった資料だけを追加する。

## 変更内容

```text
docs/
├── README.md
├── requirements.md
├── proposal.md
├── plans/
│   ├── README.md
│   └── 0001_docs-refactor/
│       └── plan.md
└── archive/
    └── proposals/
        └── 2026-08-23/
            └── alternatives/
                ├── proposal_claude.md
                └── proposal_codex.md
```

移動対応は次のとおり。

| 移動前 | 移動後 |
|---|---|
| `docs/proposal_claude.md` | `docs/archive/proposals/2026-08-23/alternatives/proposal_claude.md` |
| `docs/proposal_codex.md` | `docs/archive/proposals/2026-08-23/alternatives/proposal_codex.md` |

## 実施手順

- [x] `docs` の索引を追加する。
- [x] `plans` の命名規則と運用方法を追加する。
- [x] 比較検討に使用した提案書をアーカイブへ移動する。
- [x] `requirements.md` を目的別に再構成する。
- [x] 正本の内容と参照関係を検証する。

## 完了条件

- `docs/README.md` から現在の要件、提案、プラン、アーカイブへ移動できる。
- `proposal.md` と `requirements.md` が現在の正本として区別されている。
- 比較検討用の2案が正本と同じ階層に存在しない。
- 新しい変更を `0002_...` として追加できる運用ルールが文書化されている。
- 再構成後の `requirements.md` に元の実質的な要件がすべて残っている。
