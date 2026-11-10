# util — claude-wrapper 共通ヘルパー

独立スクリプトではなく、隣のサブフォルダ（`minimal_agent/`、`todo_runner/`、`todo_detail_runner/`、これから足すもの）から import する共有コード。セットアップは親の [`../AGENTS.md`](../AGENTS.md) を参照。

パッケージ化しない。各スクリプトは `claude-wrapper` ルートを `sys.path` に入れてから `from util.models import ...` する。

## ファイル

- `models.py` — [`models.json`](models.json) の読み込み・バリデーション・タスク model の正規化
- `models.json` — 許可するモデル id と、ユーザーが書く評価（default / 用途）。手で直す
- `test_models.py` — カタログ読み込みと正規化の単体テスト

## 使い方（隣のサブフォルダから）

スクリプトは `tools/claude-wrapper/<project>/foo.py` に置く。親ディレクトリを path に入れる:

```python
import sys
from pathlib import Path

_WRAPPER_ROOT = Path(__file__).resolve().parents[1]
if str(_WRAPPER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WRAPPER_ROOT))

from util.models import load_catalog
```

同一サブフォルダにモジュールが複数あるときは、上記をそのフォルダの `_paths.py` に一度だけ書き、他は `import _paths` してから `from util.models import ...` する（`todo_detail_runner/_paths.py` がその例）。

```python
catalog = load_catalog()
# catalog.default_id          — --model 省略時の既定
# catalog.is_allowed(id)      — カタログ外なら拒否
# catalog.allowed_text()      — ヘルプ用の id 列挙
# catalog.prompt_block()      — エージェントへ渡す id + 評価
# normalize_model(value, fallback, catalog)  — 空なら fallback、不明なら error
```

許可 id を足す・評価を直すときは `models.json` だけ編集する。カタログの形が壊れている（default が 1 件でない、id 重複、evaluation 空）と `load_catalog()` が失敗する。

## `models.json` のフィールド

- `id` — エージェントと todo.json が書く値。CLI / SDK に渡す
- `resolved` — 直近の CLI 確認で `modelUsage` に出た解決先（情報。実行には使わない）
- `default` — ちょうど 1 件だけ `true`。`--model` 省略時と、タスクが model を省略したときの既定
- `role` — 短い分類（`simple` / `daily` / `complex` など）。エージェントが選びやすくする
- `evaluation` — ユーザーの評価メモ。plan / split のプロンプトに載せる

確認した実体（Claude Code CLI 2.1.233、2026-09-12、公式 [model-config](https://code.claude.com/docs/en/model-config) と突き合わせ）:

| カタログ id  | CLI が解決した名前          |
| ------------ | --------------------------- |
| `haiku`      | `claude-haiku-4-5-20251001` |
| `sonnet`     | `claude-sonnet-5`           |
| `opus`       | `claude-opus-5`             |
| `fable`      | `claude-fable-5`            |
| `sonnet[1m]` | `claude-sonnet-5[1m]`       |
| `opus[1m]`   | `claude-opus-5[1m]`         |

未知の文字列は CLI が `[claude-code:unrecognized_model]` で拒否する。`default` / `best` / `opusplan` も CLI 上は動くが、アカウント依存や plan/実行の切替なのでカタログには入れていない。ピン留めのフルネームが要るときは `models.json` にエントリを足す。PowerShell では `sonnet[1m]` のような括弧付き id を `"sonnet[1m]"` と引用すること。

## テスト

```powershell
cd tools\claude-wrapper\util
python -m unittest test_models
```
