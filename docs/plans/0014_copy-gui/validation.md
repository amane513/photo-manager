# 0014 検証記録

実施日: 2026-09-13

## 段階1: 現状と実機互換性の確認

### 現行実装

- `service.execute_copy()`は配置計画、既存内容照合、転送、全件検証と構造化結果を担い、CLIから独立している。
- プロファイル解決、ホスト設定からの保存先補完、転送実装の生成と`close()`、タイムゾーンの解決、JSONログ保存、利用者向け成功判定は`cli.py`に残っている。
- `result_as_dict()`は`schema_version = 2`のJSON互換結果を生成するが、開始・終了時刻、プロファイル、ホスト設定、ログディレクトリ、タイムゾーン、rsyncバージョンはCLIが後から付加している。
- `execute_copy()`と`verify_copy()`は完了結果だけを返し、処理中の通知を行わない。
- `metadata.py`は`exiftool`、`rsync.py`は`ssh`を固定名で起動する。`RsyncSshTransfer`のrsyncだけは実行ファイルを注入可能である。
- 現在の`~/.config/photo-copy/profiles.ini`にある`host-config`は`./scripts/hosts/ubuntu-amane-yajima.env`であり、リポジトリルートのカレントディレクトリに依存する。

### 実機環境

| 項目 | 確認値 | 結果 |
|---|---|---|
| macOS | 26.6.2 (Build 25G83)、arm64 | 対象環境 |
| Python | 3.10.13 | プロジェクト下限3.10とPySide6 wheelの条件を満たす |
| PySide6 / Qt | 6.11.2 / 6.11.2 | 一時venvでQt Widgetsをoffscreen起動できた |
| PySide6 wheel | `cp310-abi3-macosx_13_0_universal2` | arm64とPython 3.10に適合した |
| `pyside6-deploy` | 6.11.2同梱 | `.app`、`standalone`、`--dry-run`のオプションを確認した |
| ExifTool | 13.55 (`/opt/homebrew/bin/exiftool`) | 現行CLIの確認値と一致した |
| rsync | 3.5.0 (`/opt/homebrew/bin/rsync`) | 下限3.2.4を満たす |
| OpenSSH | 10.3p1 (`/usr/bin/ssh`) | 現行のControlMaster方式で使用する |
| macOS構築ツール | Command Line Tools、`dyld_info`、`codesign` | `pyside6-deploy`の構築前提を満たす |

PySide6はプロジェクトの`.venv/`へ導入せず、`/tmp`配下に作った一時venvだけで確認した。実アプリの構築、署名、Finder／Dock起動は段階4〜5で確認する。

### 公式情報との照合

- Qt for Pythonの[Deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)は、デスクトップ向けの公式手段として`pyside6-deploy`を案内している。
- [`pyside6-deploy`の公式文書](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)は、macOSで`.app`を生成し、設定ファイル、`standalone`モード、dry-runを利用できることを示している。
- [PyPIのPySide6 6.11.2](https://pypi.org/project/PySide6/6.11.2/)には、CPython 3.10以上、macOS 13以上、universal2のwheelがある。

### 段階1で実データへ行った操作

なし。SDカード、Ubuntu主HDD、写真ライブラリ、既存ログ、既存プロファイルを変更していない。

### 回帰確認

```sh
.venv/bin/python -m unittest discover -s tests
./scripts/mac/verify-copy-cli.sh --project-root .
git diff --check
```

結果: 119 tests passed。CLI環境の検査と差分の空白検査も成功した。
