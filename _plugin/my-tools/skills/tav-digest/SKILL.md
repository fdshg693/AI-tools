---
name: tav-digest
description: tav`で`--topic`指定して収集した`pages/`(extract/crawl/search-extract/map-extractの取得本文)のうち、自分で1件ずつ読む代わりに`aim --parallel`で並列にAI抽出させたいものをまとめて処理し、関連する内容だけを報告させるCLI連携スキル。(a) `pages/index.json`のエントリ数が多くタイトルだけでは関連性を判断しづらい場合(目安5件以上)に全件を渡して関連するものだけ絞り込ませたいとき、(b) `index.json`から読みたいファイルを選んだ後、その中に`char_count`が大きいファイルが複数あり個別Readせずまとめて抽出させたいとき、のいずれかで使う。1ファイルだけを抽出したい場合は`aim-cli`を直接使えばよい。discovery(`search/`・`map/`)やreport(`research/`)はこのスキルの対象外(集約1ファイル、または成功時のみの単一レポートなのでそのまま読めば足りる)。

# 前提条件(このスキル自体はインストール・セットアップを一切行わない):
#   - `tav` コマンドが PATH 上で使えること
#     (セットアップは tools/tav-cli/README.md 参照)
#   - `aim` コマンドが PATH 上で使え、OPENROUTER_API_KEY が設定済みであること
#     (セットアップは tools/_plugin/my-tools/skills/aim-cli/SKILL.md 参照)
#
# 依存スキル: tools/_plugin/my-tools/skills/tav-cli (収集本体)
#            tools/_plugin/my-tools/skills/aim-cli (並列AI抽出本体)
# このスキルは上記2つを繋ぐ薄いオーケストレーション層で、自前のソースコードは持たない。
meta:
  tag: []
  requires_repo_tools: tav, aim
  requires_env: OPENROUTER_API_KEY
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: tav-cli, aim-cli
  status: stable
  description: no description
  version: 1.0.6
---

## 全体の流れ

```markdown
1. tav extract / crawl / search-extract / map-extract ... --topic <topic> を実行する
   → <TAVILY_OUTPUT_DIR>/<topic>/pages/ に本文 .md と index.json が書かれる(個別
   ファイルの本文はターミナルには出ない。discovery役割の search/・map/、report役割の
   research/ はこのスキルの対象外 — それぞれ集約1ファイル・成功時のみの単一レポート
   なのでそのまま Read すればよい)

2. pages/index.json を Read し、entries(file・url・title・title_source・char_count)
   一覧を把握する。ここで aim に渡す対象を決める:
   (a) タイトルだけでは関連性が判断しづらい・件数が多い(目安5件以上) → 全件を渡す
   (b) すでに読みたいファイルはタイトルから絞れている → その中で char_count が
   大きいものだけを渡す(小さいものはそのまま個別に Read すればよく、この
   スキルは使わない)

3. 元の質問/知りたいことを1本の「抽出プロンプト」に言語化する(下記「抽出プロンプトの
   作り方」参照)。ファイルごとに指示を変える必要は通常ないので、同じ抽出文を各
   `--prompt` に繰り返す。ファイル名や個々のタイトルはプロンプトに埋め込まない

4. 本実行の前に、手順2で選んだ結果ファイルのうち1件だけを
   `aim --prompt "<抽出プロンプト> @<1件のパス>"`で投げ、
   エラーなく応答が返ることを確認する(モデル側の問題を全件投入前に切り分けるため。
   下記「注意点」参照)

5. 手順2で選んだエントリの`file`を`pages/`と結合したパスを、ファイルごとに1つの
   `--prompt` として"まとめて1回"aimに渡す
   aim --parallel --jobs <並列数> --prompt "<抽出プロンプト> @<topic_dir>/pages/0001-....md" "<抽出プロンプト> @<topic_dir>/pages/0002-....md" ...
   → 1コマンドで選んだ結果への並列AI呼び出しが走り、ファイルごとの応答が返る。
   Claude自身が個別ファイルをReadする必要はない

6. aimの応答を見て、「関連なし」以外の項目だけをユーザーへの回答に統合する。
   出典URLは、aimの応答が返す`file`パス(または`path`)を手順2で読んだ
   `pages/index.json`の`file`と突き合わせて`url`を引けばよい(tavのページ本文は
   `# title` + 本文のみでURL行を持たないため、mslearn側と違い応答本文からの転記
   指示はプロンプトに含めない。追加のReadは不要)

7. 抜粋だけでは情報不足な場合だけ、`pages/index.json`の`url`を`tav extract`で
   再取得する(`--detail max`や`--query`なしでの全文取得など)か、必要なら同じ要領で
   aim(1ファイルのみでも可)に該当箇所を抽出させる
```

手順1・2・7は `tav-cli` スキル(`tools/_plugin/my-tools/skills/tav-cli/SKILL.md`)と
完全に同じ挙動。オプション・出力レイアウト・終了コードなどの詳細はそちらを参照し、
ここでは重複させない。

## 抽出プロンプトの作り方

`--parallel` はプロンプトごとに独立した指示を使える。抽出では同じ指示を各 `--prompt`
に繰り返すのが基本（ファイルごとに変えなくてよい）。「何を探しているか」をファイル
非依存の形で言語化するのがコツ。指示と対象 `@path` を1プロンプトにまとめて、ファイル
の数だけ並べる。

例: ユーザーの質問が「Microsoft Fabric の OneLake と Lakehouse の違い」の場合

```text
以下はWeb調査で取得したページ本文の抜粋です。
「Microsoft Fabric の OneLake と Lakehouse の違い」に関連する記述があれば、
該当箇所を日本語で簡潔に抜き出してください。
関連する記述が無ければ、他には何も書かず「関連なし」とだけ答えてください。
```

- ❌ 単に「要約してください」だけだと、無関係な結果まで律儀に要約されてしまいフィルタ
  リングにならない。**「関連が無ければ関連なしとだけ答える」を必ず明示する**
- 抜粋が途中で切れている(`--query`付き抽出時のチャンク境界`[...]`など)、情報が
  不十分そうな兆候を拾いたい場合は、抽出プロンプトに「情報が不十分そうなら
  『要フルページ再取得』と付記して」も足しておくと、手順7に進むべきファイルを
  aimの応答だけから判断できる

## 並列数(`--jobs`)の目安

- `pages/`の件数は`--detail`プリセットや対象コマンド(`extract`の指定URL数、`crawl`の
  `limit`、`search-extract`/`map-extract`の絞り込み件数)次第でまちまち。`aim --parallel`の
  既定`--jobs 4`でも十分速いが、件数が多い/急ぎなら`--jobs 8`〜`10`(上限)
  まで上げてよい。`--jobs`は`--parallel`専用
- 同じ`--topic`に対して複数回`extract`/`crawl`を実行し`pages/`が積み上がっている
  場合も、選んだ全ファイルを1回の`aim --parallel`呼び出しに `--prompt` として並べて
  渡せば同様に並列化される
- `--jobs`を上げても速くなるのはAI呼び出しが正常に進む場合のみ。既定モデルが利用
  不可などモデル/API側に問題がある場合は全ファイルが同じエラーで即失敗するだけなので、
  まず「注意点」の1件スモークテストで切り分ける

## 使い分け: このスキル vs `tav-cli` スキル

| 状況                                                                   | 使うスキル                                          |
| ---------------------------------------------------------------------- | --------------------------------------------------- |
| `pages/`の件数が1〜2件で、内容もすぐ読める規模                         | `tav-cli`(直接Readした方が単純)                     |
| `index.json`でタイトルから選んだファイルが小さい(`char_count`が少ない) | `tav-cli`(そのまま個別に Read)                      |
| `pages/`の件数が多くタイトルだけでは関連性を判断しづらい(目安5件以上)  | `tav-digest`(このスキル・全件投入)                  |
| `index.json`で選んだファイルの中に`char_count`が大きいものが複数ある   | `tav-digest`(このスキル・選んだ分だけ投入)          |
| discovery(`search/`・`map/`)やreport(`research/`)を読みたいだけ        | `tav-cli`(集約1ファイル/単一レポートをそのまま読む) |

いずれの場合も判断は必ず `pages/index.json` を Read した後に行う(`tav`実行直後に
返るのはstderrの「Wrote ... .md file(s) to ...」通知のみで、集計値は返らない)。
「大きい」の閾値は会話の残りコンテキスト量や個別ファイルの内容次第で変わるため固定値は
なく、`index.json`に付記された各エントリの`char_count`を見て都度判断する。

## 注意点

- `aim --parallel`はステートレスでDB永続化はしない。同じトピックを再処理する場合は都度
  呼び直すことになる(`pages/`配下のファイル自体は`--topic`のトピックフォルダに
  残るため再利用は可能)
- 個別ファイルの読み込み失敗・AI呼び出し失敗は、そのプロンプトだけ失敗として記録され
  他ファイルの処理は継続する(`aim-cli`スキル参照)。失敗したファイルは`tav extract`
  など代替手段で個別に読む
- `tav`/`aim`双方のインストール手順・環境変数・終了コードなどのセットアップ/仕様は
  このスキルでは扱わない。未設定エラーが出た場合はそれぞれのスキルの案内に従う
- **全ファイルが同一のエラーメッセージで失敗した場合は、個別ファイルの問題ではなく
  モデル/API側の問題を疑う**(例: 既定の無料枠モデルが提供停止でOpenRouter呼び出しが
  全滅する、など)。この場合は手順7の個別フォールバック(`tav extract`)に進んでも
  無意味なので、`--model`に別のモデル略記(`aim --list-models`参照)を明示して
  全件を再実行する
