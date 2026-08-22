# 作業計画

このディレクトリには、実装・修正・移行など、完了までの間だけ必要な作業文書を置く。現行仕様の正本ではない。

## 命名

```text
<4桁連番>-<短い目的>/README.md
```

例:

```text
0002-review-remediation/README.md
0003-add-phone-import/README.md
```

番号は作業計画の作成順で割り当て、削除後も再利用しない。フォルダ名は英小文字のkebab-caseとする。

## 内容

各計画の `README.md` 冒頭に、少なくとも次を記載する。

```markdown
# Plan title

- Status: Draft | Active | Blocked
- Created: YYYY-MM-DD
- Updated: YYYY-MM-DD
- Exit criteria: 完了を判断できる条件
```

最初は `README.md` だけを作る。調査結果や受け入れ記録が独立して長くなる場合だけ、`findings.md` や `acceptance.md` を同じフォルダへ追加する。

## ライフサイクル

1. 作業開始時に計画を作り、`Status: Active` にする。
2. 作業中に仕様変更が確定したら `specification/` を更新する。
3. 長期的に理由を残す必要がある判断は `decisions/` へADRとして記録する。
4. 実装構造や安全上の不変条件が変わったら `architecture.md` を更新する。
5. 終了条件を満たしたら恒久文書への反映を確認し、計画フォルダを削除する。

完了済み計画の `archive/` は原則として作らない。過去の計画や経緯はGit履歴で確認し、現在の検索結果に古い指示を混ぜないようにする。監査上、実行結果そのものの保存が必要になった場合だけ、その目的を明示した恒久文書として別途設計する。
