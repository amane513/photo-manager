# 変更プラン

変更ごとに、次の形式でフォルダを追加する。

実施済みと今後予定しているプランの一覧は、[future_plans.md](future_plans.md)を参照する。

```text
NNNN_short-description/
└── plan.md
```

例:

```text
0001_docs-refactor/
0002_initial-immich-setup/
0003_backup-workflow/
```

## 命名規則

- `NNNN` は作成順の4桁連番とし、一度採番した番号は変更・再利用しない。
- 説明部分は、英小文字のkebab-caseを基本とする。
- 完了、保留などの状態はフォルダ名に含めず、`plan.md` に記録する。
- 番号は識別子であり、優先度や実施順を表さない。

## 基本構成

小さな変更は `plan.md` だけで完結させる。必要な場合に限り、次のファイルやフォルダを追加する。

- `decisions.md`: 実施中に生じた重要な判断
- `validation.md`: テストや検証の詳細
- `assets/`: 図、サンプル設定などの付属資料

完了したプランも、変更理由と判断を追跡できるよう削除せずに残す。
