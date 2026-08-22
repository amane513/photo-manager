# photo-manager documentation

このディレクトリには、photo-manager の現行仕様、恒久的な設計情報、設計判断、進行中の作業計画を置く。

## 正本

文書の役割は次のとおり。

| 読みたい内容 | 文書 |
|---|---|
| 目的、スコープ、保存構成、安全原則 | [`specification/overview.md`](specification/overview.md) |
| 取り込み対象、日時、命名、コピー、eject | [`specification/import.md`](specification/import.md) |
| チェックサム、verify、mirror | [`specification/integrity.md`](specification/integrity.md) |
| 設定、CLI、終了コード | [`specification/cli-and-config.md`](specification/cli-and-config.md) |
| モジュール境界と実装上の不変条件 | [`architecture.md`](architecture.md) |
| 重要な判断とその理由 | [`decisions/README.md`](decisions/README.md) |
| 進行中の実装・修正計画 | [`plans/`](plans/) |

利用者向けのセットアップと日常的な操作は、リポジトリルートの [`README.md`](../README.md) を参照する。

## 更新方針

- `specification/` は現在の外部仕様を記述する。実装と仕様の差が判明した場合は、どちらを正すか判断して同じ変更で同期する。
- `architecture.md` は実装の構造と、複数モジュールにまたがる安全性の不変条件を記述する。個々の関数の説明はコードへ置く。
- `decisions/` は後から覆りうる重要な判断を1判断1ファイルで記録する。採番は4桁の通番とし、欠番を再利用しない。
- `plans/` は作業中だけ必要な文書を置く。完了時は恒久的な内容を仕様・設計・ADRへ反映してから計画を削除し、履歴はGitに任せる。
- 文書は行数だけで分割せず、「どの問いに答えるか」で分ける。300行を超えた場合は責務の混在を見直し、短い関連文書が増えた場合は統合を検討する。

仕様と一時計画が食い違う場合、仕様が現在の契約であり、計画は仕様を変更する提案または実装手順として扱う。仕様変更を確定するときは、必要に応じてADRを追加する。
