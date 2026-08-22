# Architecture Decision Records

このディレクトリには、互換性、安全性、データ解釈、永続形式に関わる重要な判断を1判断1ファイルで記録する。

| ADR | Status | 判断 |
|---|---|---|
| [0002](0002-checksum-ledger-format.md) | Accepted | `checksums.tsv` の永続形式 |
| [0003](0003-managed-part-location.md) | Accepted | 管理用一時ファイルの配置と正式化 |
| [0004](0004-quicktime-capture-time.md) | Accepted | XMLがない動画のQuickTime撮影日時解釈 |

ファイル名は `<4桁連番>-<kebab-case-title>.md` とする。番号は識別子であり、欠番を埋めるためのリネームや再利用はしない。

各ADRは原則として次の構成を持つ。

```markdown
# ADR NNNN: title

## Status

Proposed | Accepted | Superseded

## Context

## Decision

## Consequences
```

採用済みの判断を変更する場合、既存ADRを現在の結論へ書き換えず、新しいADRから置き換え対象を示す。単なる実装手順、進捗、短期的な調査メモは [`../plans/`](../plans/) に置く。
