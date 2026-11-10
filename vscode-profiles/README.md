# vscode-profiles

VS Code stable のユーザープロファイルごとに、`settings.json` のトップレベルキーの有無と差を見る。指定したキーは、ソースのプロファイルの値で宛先へ上書きできる。

ワークスペースの `.vscode/settings.json`、拡張機能の有効化、キーバインド、Cursor、Insiders は対象外。

## インストール

リポジトリルートから、グローバル CLI としてエディタブルインストールする。

```powershell
uv tool install --editable tools/vscode-profiles
```

テストはリポジトリルートから実行する。一時ディレクトリのフィクスチャだけを使い、実在のユーザーデータは開かない。

```powershell
uv run pytest tools/vscode-profiles/tests
```

## 使い方

ユーザーデータディレクトリの既定は、Windows なら `%APPDATA%\Code`、macOS なら `~/Library/Application Support/Code`、Linux なら `~/.config/Code`。`--user-data-dir` で差し替えられる。

```powershell
vscode-profiles --version
vscode-profiles list
vscode-profiles diff
vscode-profiles diff --key editor.fontSize
vscode-profiles diff --key editor.fontSize --key editor.tabSize
vscode-profiles diff --prefix claudeCode.
vscode-profiles apply --from Default --to Python --key editor.fontSize
vscode-profiles apply --from Default --to all --prefix claudeCode. --write
vscode-profiles --user-data-dir D:\Code list
```

- `--version` — マニフェストの版数を1行出す。ユーザーデータは読まない。
- `list` — プロファイル名、設定を継承しているか、独自設定のトップレベルキー数。設定値は出さない。
- `diff` — 独自設定を持つプロファイルだけを比べる。キー名と状態だけ出す。
- `--key` / `--prefix` — `diff` では付けたときだけ、そのキーの値も出す。`--key` は繰り返せる。両方付けたときは、名前が一致し、かつプレフィックスで始まるキーだけ。
- `apply` — ソースの指定キーを宛先へ上書きする。既定は変更予告だけで、`--write` のときだけファイルを変える。

プロファイル名は台帳の `name`。デフォルトは `Default`。フォルダ id は、同名が複数あるときの失敗メッセージ以外には出さない。同名なら location を出して終了コード 1 で止まる。デフォルトの location 表示は `(default)`。

`useDefaultFlags.settings` が真のプロファイルは `inherit` として `list` に出す。独自の `settings.json` は読まない。キー数は 0。`diff` の比較には入れない。

設定の実体は、デフォルトが `User/settings.json`、名前付きが `User/profiles/<location>/settings.json`。`location` は `builtin/agents` のように `/` を含み得る。解決後のパスが `User/profiles` の外になる location は拒否する。

`settings.json` は JSONC（コメントと末尾カンマ）として読む。キーはトップレベルだけ。`[typescript]` もその1キー。

### `list` の列

タブ区切り。`Default` が先で、残りは名前の順。

```text
Default	own	56
java	inherit	0
```

`own` は独自の `settings.json` を持つ。`inherit` は設定をデフォルトから継承している。

### `diff` の状態

比較している独自設定の和集合について、各キーを次のどれか一つにする。

| 状態 | 意味 |
| --- | --- |
| `same` | 比較中の全員がそのキーを持ち、値が同じ |
| `missing` | 一部に無く、持っているプロファイルの値は同じ |
| `different` | 持っているプロファイル同士で値が違う |

キーも `--prefix` も無いときは `キー<TAB>状態` だけ。

```text
editor.fontSize	same
python.defaultInterpreterPath	different
```

`--key` または `--prefix` があるときは、3列目にプロファイル名から値への JSON オブジェクトを足す。そのプロファイルにキーが無いときは `null`。並びは `list` と同じで、継承プロファイルは入らない。

```text
editor.fontSize	same	{"Default": 14, "Python": 14}
```

`--prefix` はトップレベルキーの前方一致。`claudeCode.` は `claudeCode.selectedModel` に一致し、`claudeCodeExtra` には一致しない。

一致が0件のときは何も出さず終了コード 0。空の `--key` や `--prefix` は終了コード 2。

### `apply`

`--from` は必須。値はそのプロファイルの独自 `settings.json` から取る。継承プロファイルを `--from` や `--to` に指定すると失敗し、ファイルは変えない。デフォルトの中身は辿らない。

`--to` は繰り返す。`--to all` は、独自設定を持つプロファイルのうちソース以外。継承プロファイルは含めず、`skip<TAB>名前` を出す。

`--key` を繰り返すか、`--prefix` でソースに実在するトップレベルキーを選ぶ。前方一致は `diff` と同じ。宛先にしか無いキーは含めない。`--key` のどれかがソースに無ければ、宛先はどれも変えない。`--prefix` の一致が 0 件なら何も書かず失敗する。`--key` と `--prefix` を両方付けたときは、名前が一致し、かつプレフィックスで始まるキーだけ。キーもプレフィックスも無いときは終了コード 2。

オブジェクトと配列は、そのトップレベルキーごと入れ替える。深いマージはしない。宛先の値が同じキーは `same` として数え、ファイルには書き戻さない。`true` と `1` は別の値。オブジェクトのキー順の違いだけでは `same`。

`--write` が無い実行は、宛先ごとに操作を出す。並びは `list` と同じで、キー名は昇順。

```text
skip	java
Python	editor.fontSize	replace	14	16
Python	editor.tabSize	add	4
Python	files.eol	same	"\n"
```

列は `宛先`、`キー`、`add` / `replace` / `same`、ソースの値。`replace` のときだけ、最後に宛先の今の値を足す。値は JSON。

`--write` は、全宛先の新しい内容をメモリ上で作ってからバックアップを取り、その後に置換する。編集箇所を特定できないファイル（トップレベルキーの重複など）は、どの宛先も変えない。バックアップはプロファイルディレクトリの外、OS のユーザーキャッシュ配下の `vscode-profiles/backups/` に取る。変わった宛先ごとに `backup<TAB>名前<TAB>パス` を出す。置換は一時ファイルへ書いてから入れ替える。途中の宛先で失敗したら、そのファイルをバックアップから戻し、残りの宛先は置換しない。`restore<TAB>名前<TAB>ok` または `failed` を出す。

`--write` は VS Code stable（Windows では `Code.exe`、それ以外ではプロセス名 `Code` または `code`）が動いていて、実際に変えるキーがあるとき失敗する。`--force` のときだけ続行する。同じ値しか無い実行はプロセスを見ない。

`storage.json`、キーバインド、スニペットは読んでも書かない。コメント、触らないキー、キー順、末尾カンマは残す。足すキーはトップレベルの末尾に置く。

## 終了コード

| コード | 意味 |
| --- | --- |
| 0 | 成功 |
| 1 | 台帳や設定を読めない、同名プロファイル、location がプロファイルディレクトリの外、`apply` のソース不足・継承の指定・編集不能・起動中の VS Code |
| 2 | 使い方 |

## ファイル構成

- `vscode_profiles/cli.py` — `list` / `diff` / `apply` / `--version`
- `vscode_profiles/apply.py` — キーの上書き、JSONC を保持した編集、バックアップ
- `vscode_profiles/profiles.py` — ユーザーデータディレクトリ、台帳、設定パス
- `vscode_profiles/jsonc.py` — JSONC の読み取り
- `vscode_profiles/diff.py` — キーの状態
- `tests/` — 一時ディレクトリだけを使う
