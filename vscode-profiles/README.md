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
vscode-profiles diff --prefix claudeCode. --exclude-key claudeCode.environmentVariables
vscode-profiles diff --key claudeCode.environmentVariables --mask
vscode-profiles diff --prefix claudeCode. --by-profile
vscode-profiles apply --from Default --to Python --key editor.fontSize
vscode-profiles apply --from Default --to all --prefix claudeCode. --write
vscode-profiles --user-data-dir D:\Code list
```

- `--version` — マニフェストの版数を1行出す。ユーザーデータは読まない。
- `list` — プロファイル名、設定を継承しているか、独自設定のトップレベルキー数。設定値は出さない。
- `diff` — 独自設定を持つプロファイルだけを比べる。キー名と状態だけ出す。
- `--key` / `--prefix` — `diff` では付けたときだけ、そのキーの値も出す。`--key` は繰り返せる。両方付けたときは、名前が一致し、かつプレフィックスで始まるキーだけ。
- `--exclude-key` — `diff` と `apply` で、選んだキーから外すトップレベルキー。繰り返せる。`--key` / `--prefix` が無い `diff` でも効く。
- `--mask` — `diff` と `apply` で、出力する値の中の文字列を `"***"` に置き換える。オブジェクトのキー名、配列の長さ、数値・真偽値・`null` は残す。状態（`same` など）の判定は伏せる前の値で行う。トークンを含みうる `claudeCode.environmentVariables` のようなキーを見るときに付ける。
- `apply` — ソースの指定キーを宛先へ上書きする。既定は変更予告だけで、`--write` のときだけファイルを変える。
- `remove` — 指定キーをプロファイルから消す。予告と `--write` は `apply` と同じ。

プロファイル名は台帳の `name`。デフォルトは `Default`。フォルダ id は、同名が複数あるときの失敗メッセージ以外には出さない。同名なら location を出して終了コード 1 で止まる。デフォルトの location 表示は `(default)`。

`useDefaultFlags.settings` が真のプロファイルは `inherit` として `list` に出す。独自の `settings.json` は読まない。キー数は 0。`diff` の比較には入れない。

設定の実体は、デフォルトが `User/settings.json`、名前付きが `User/profiles/<location>/settings.json`。`location` は `builtin/agents` のように `/` を含み得る。解決後のパスが `User/profiles` の外になる location は拒否する。

### WSL の Machine 設定（`--wsl`）

Windows で `--wsl <ディストリビューション名>` を付けると、その WSL の VS Code Server の Machine 設定（`~/.vscode-server/data/Machine/settings.json`）を疑似プロファイル `WSL:<名前>` として末尾に足す。`list` / `diff` / `apply` / `remove` のどれでも使え、`--from` / `--to` / `--profile` に `WSL:<名前>` と書ける。`--to all` / `--profile all` にも入る。繰り返せる。

```powershell
vscode-profiles --wsl Ubuntu-24.04 diff --prefix claudeCode. --by-profile
vscode-profiles --wsl Ubuntu-24.04 apply --from Default --to WSL:Ubuntu-24.04 --prefix claudeCode. --exclude-key claudeCode.environmentVariables
```

- パスは `wsl.exe -d <名前>` で WSL 側の `$HOME` を聞き、`\\wsl.localhost\<名前>\...` に組み立てる。WSL を起動するので少し待つ。Windows 以外と、名前に英数字・`.`・`_`・`-` 以外を含むときは終了コード 2
- Machine 設定は台帳もプロファイルも持たない 1 ファイル。`list` の 2 列目は `machine`。ファイルが無ければキー 0 個として扱い、`apply --write` で作る（`Machine` フォルダが無いと失敗する）
- 書き込みは他のプロファイルと同じ（一時ファイル→入れ替え、改行コードは元のまま）。バックアップは `backups/<時刻>/_machine/WSL_<名前>/settings.json`
- 起動中チェックは Windows の `Code.exe` だけを見る。VS Code Server は Remote 接続中にしか動かず、Machine 設定を書き換えるのは設定 UI で編集したときだけなので、Windows 側の VS Code を閉じれば足りる
- VS Code Server のデータディレクトリを `--user-data-dir` に渡しても使えない。そこには台帳はあるが `User/settings.json` が無く、ユーザー設定は Windows 側にある

`settings.json` は JSONC（コメントと末尾カンマ）として読む。キーはトップレベルだけ。`[typescript]` もその1キー。

### `list` の列

タブ区切り。`Default` が先で、残りは名前の順。

```text
Default	own	56
java	inherit	0
```

`own` は独自の `settings.json` を持つ。`inherit` は設定をデフォルトから継承している。`machine` は `--wsl` で足した Machine 設定。

### `diff` の状態

比較している独自設定の和集合について、各キーを次のどれか一つにする。

| 状態        | 意味                                         |
| ----------- | -------------------------------------------- |
| `same`      | 比較中の全員がそのキーを持ち、値が同じ       |
| `missing`   | 一部に無く、持っているプロファイルの値は同じ |
| `different` | 持っているプロファイル同士で値が違う         |

キーも `--prefix` も無いときは `キー<TAB>状態` だけ。

```text
editor.fontSize	same
python.defaultInterpreterPath	different
```

`--key` または `--prefix` があるときは、3列目にプロファイル名から値への JSON オブジェクトを足す。そのプロファイルにキーが無いときは `null`。並びは `list` と同じで、継承プロファイルは入らない。

```text
editor.fontSize	same	{"Default": 14, "Python": 14}
```

`--mask` を付けると、値の中の文字列が `"***"` になる。

```text
claudeCode.environmentVariables	missing	{"Default": [{"name": "***", "value": "***"}], "Python": null}
```

`--by-profile` を付けると、3列目は値の代わりに、プロファイル名から「値のグループ番号」への JSON オブジェクトになる。同じ値のプロファイルは同じ番号（並び順で先に現れた値から 1, 2, …）、キーが無いプロファイルは `null`。値は一切出さないので、秘密を含むキーでも `apply` の宛先を決められる。`--key` / `--prefix` / `--mask` と一緒に付けても値は出さない。

```text
claudeCode.selectedModel	different	{"Default": 1, "Node": null, "Python": 2, "azure": 1}
```

値の比較は JSON として行う。`true` と `1` は別の値で、オブジェクトのキー順の違いだけなら同じ値（`apply` と同じ）。

`--prefix` はトップレベルキーの前方一致。`claudeCode.` は `claudeCode.selectedModel` に一致し、`claudeCodeExtra` には一致しない。

一致が0件のときは何も出さず終了コード 0。空の `--key`・`--prefix`・`--exclude-key` は終了コード 2。

### `apply`

`--from` は必須。値はそのプロファイルの独自 `settings.json` から取る。継承プロファイルを `--from` や `--to` に指定すると失敗し、ファイルは変えない。デフォルトの中身は辿らない。

`--to` は繰り返す。`--to all` は、独自設定を持つプロファイルのうちソース以外。継承プロファイルは含めず、`skip<TAB>名前` を出す。

`--key` を繰り返すか、`--prefix` でソースに実在するトップレベルキーを選ぶ。前方一致は `diff` と同じ。宛先にしか無いキーは含めない。`--key` のどれかがソースに無ければ、宛先はどれも変えない。`--prefix` の一致が 0 件なら何も書かず失敗する。`--key` と `--prefix` を両方付けたときは、名前が一致し、かつプレフィックスで始まるキーだけ。`--exclude-key` に挙げたキーは最後に外す。外した結果 0 件なら何も書かず失敗する。キーもプレフィックスも無いときは終了コード 2。

オブジェクトと配列は、そのトップレベルキーごと入れ替える。深いマージはしない。宛先の値が同じキーは `same` として数え、ファイルには書き戻さない。`true` と `1` は別の値。オブジェクトのキー順の違いだけでは `same`。

`--write` が無い実行は、宛先ごとに操作を出す。並びは `list` と同じで、キー名は昇順。

```text
skip	java
Python	editor.fontSize	replace	14	16
Python	editor.tabSize	add	4
Python	files.eol	same	"\n"
```

列は `宛先`、`キー`、`add` / `replace` / `same`、ソースの値。`replace` のときだけ、最後に宛先の今の値を足す。値は JSON。`--mask` のときは `diff` と同じく文字列を伏せる（書き込む値は伏せない）。

`--write` は、全宛先の新しい内容をメモリ上で作ってからバックアップを取り、その後に置換する。編集箇所を特定できないファイル（トップレベルキーの重複など）は、どの宛先も変えない。バックアップはプロファイルディレクトリの外、OS のユーザーキャッシュ配下の `vscode-profiles/backups/` に取る。変わった宛先ごとに `backup<TAB>名前<TAB>パス` を出す。置換は一時ファイルへ書いてから入れ替える。途中の宛先で失敗したら、そのファイルをバックアップから戻し、残りの宛先は置換しない。`restore<TAB>名前<TAB>ok` または `failed` を出す。

`--write` は VS Code stable（Windows では `Code.exe`、それ以外ではプロセス名 `Code` または `code`）が動いていて、実際に変えるキーがあるとき失敗する。`--force` のときだけ続行する。同じ値しか無い実行はプロセスを見ない。

### `remove`

指定したトップレベルキーをプロファイルの独自 `settings.json` から消す。既定は予告だけで、`--write` のときだけファイルを変える。

```powershell
vscode-profiles remove --profile azure --key claudeCode.environmentVariables --mask
vscode-profiles remove --profile all --key claudeCode.environmentVariables --write
```

`--profile` は繰り返す。`--profile all` は独自設定を持つ全プロファイルで、継承プロファイルは `skip<TAB>名前` を出す。継承プロファイルを名指しすると失敗する。キーの選び方（`--key` / `--prefix` / `--exclude-key`）は `apply` と同じで、候補は対象プロファイルが持つキーの和集合。一致が 0 件なら失敗する。

```text
skip	java
Default	claudeCode.environmentVariables	absent
azure	claudeCode.environmentVariables	remove	[{"name": "***", "value": "***"}]
```

列は `プロファイル`、`キー`、`remove` / `absent`、`remove` のときだけ今の値（JSON。`--mask` で文字列を伏せる）。`absent` はそのプロファイルに無いキーで、何もしない。全員 `absent` なら書き込みもプロセス確認もせず終了コード 0。

キーの行ごと消し、前後のコメントと他のキーは残す。最後のキーを消して直前のキーに末尾カンマだけが残るときは、そのカンマも消す（元から末尾カンマの書き方なら残す）。バックアップ・置換・失敗時の復元・起動中の VS Code の扱いは `apply --write` と同じ。

### 外部ターミナル用のスクリプト（`--emit-ps1`）

`--write` は VS Code を閉じないと失敗するので、VS Code の拡張の中で動くエージェントからは書けない。`apply` / `remove` に `--emit-ps1 <パス>` を付けると、いつもの予告を出したうえで、同じ指定に `--write` を足したコマンドを PowerShell スクリプトに追記する。VS Code を閉じてから外部ターミナルで `pwsh -File <パス>` を実行する。

```powershell
vscode-profiles apply --from Default --to all --prefix claudeCode. --exclude-key claudeCode.environmentVariables --emit-ps1 apply.ps1
vscode-profiles remove --profile azure --key claudeCode.environmentVariables --mask --emit-ps1 apply.ps1
```

- ファイルが無ければ、`Code.exe` が動いていたら止める行を先頭に置いて作る（UTF-8 BOM 付き・CRLF）。あれば末尾にコマンドを足すので、複数の操作を 1 本にまとめられる
- 変える宛先が無い（全部 `same` / `absent`）ときは書かず、標準エラーに `nothing to write` を出す。書いたときは標準出力の最後に `script<TAB>パス` を出す
- コマンドは今の Python（`sys.executable`）で `-m vscode_profiles` を呼ぶ。`uv` も `vscode-profiles` の global インストールも要らず、どのディレクトリからでも動く。`--user-data-dir` は絶対パスにする
- `--force` は入れない。各コマンドが失敗したらスクリプトもそこで止まる
- `--write` と一緒には使えない（終了コード 2）
- スクリプトには値は入らない（キー名・プロファイル名だけ）。書き込む値は実行時にソースから読む

`storage.json`、キーバインド、スニペットは読んでも書かない。コメント、触らないキー、キー順、末尾カンマは残す。足すキーはトップレベルの末尾に置く。

## 終了コード

| コード | 意味                                                                                                                                                                |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0      | 成功                                                                                                                                                                |
| 1      | 台帳や設定を読めない、同名プロファイル、location がプロファイルディレクトリの外、`apply` / `remove` のソース不足・継承の指定・一致 0 件・編集不能・起動中の VS Code |
| 2      | 使い方                                                                                                                                                              |

## ファイル構成

- `vscode_profiles/cli.py` — `list` / `diff` / `apply` / `remove` / `--version`
- `vscode_profiles/apply.py` — キーの上書きと削除、JSONC を保持した編集、バックアップ
- `vscode_profiles/profiles.py` — ユーザーデータディレクトリ、台帳、設定パス
- `vscode_profiles/jsonc.py` — JSONC の読み取り
- `vscode_profiles/diff.py` — キーの状態、値の伏せ字
- `vscode_profiles/wsl.py` — `--wsl` の Machine 設定のパス解決
- `vscode_profiles/script.py` — `--emit-ps1` の PowerShell スクリプト
- `vscode_profiles/keys.py` — `--key` / `--prefix` / `--exclude-key` によるキーの選択
- `tests/` — 一時ディレクトリだけを使う
