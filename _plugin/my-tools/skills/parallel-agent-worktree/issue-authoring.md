# issue-authoring — タスクをISSUE群に分割・配置する手順（AI向け）

このファイルは、ユーザーから依頼された機能・タスクを[issue-shape.md](issue-shape.md)が定めるISSUE型（依存関係・ブランチ）に沿った複数issueへ分割し、`linear-cli create`で実際にLinearへ配置するまでの手順をまとめる。issue-shape.mdの仕様（descriptionの構造化ヘッダ、Project=タスクグループ）を前提とするため、未読なら先にそちらを読むこと。

対象は「このスキル専用の型を持つISSUE」に限定する。汎用issue全般の起票手順ではない。

## 全体の流れ

```markdown
1. タスクの分解
   依頼内容を、依存関係を意識しながら複数issueへ分解する（「分割方針」節参照）

2. グループ（Linear Project）の決定
   分解したissue群全体に対して1つのLinear Project名を決める（既存Projectを使うか、
   新規Projectが必要ならユーザーに事前作成を依頼する。linear-cliにproject作成コマンドは無い）

3. ブランチ・依存関係の設計
   issueごとに branch:<slug> / depends_on / base_branch を割り当てる
   （「分割方針」節のルールに従う）

4. セルフチェック
   作成前に「セルフチェック項目」節の3点を確認する

5. Linear作成（依存順）
   depends_on で参照される先行issueから順に、linear-cli create で1件ずつ作成する
   （後続issueのdepends_onには、直前に作成したissueが返すidentifierを使う）

   linear-cli create --title "<タイトル>" --team <team> --project "<グループ名>" \
   --description "$(構造化ヘッダ + 本文)"

6. ユーザーへの報告
   作成したissue群の依存関係グラフ（どれがどれに依存し、どれが同じbranchか）を要約し、
   ユーザーにレビューを促す（「report後の扱い」節参照）
```

## 分割方針

- 同じファイル・モジュールを触る一連の作業は、同じ `branch:<slug>` ＋ `depends_on` チェーンで直列化する。目的はマージコンフリクト回避であり、並行編集を避けたい作業だけを直列化すればよい
- 互いに独立したファイル・モジュールを触る作業は、別々の `branch:<slug>` に分けて並行実装を許す。無条件に全issueを1本のブランチへ直列化すると、並行実行のメリットが失われる
- 単発issue（依存が無い1件だけの作業）にも、自分専用の `branch:<slug>` を割り当てる（issue-shape.mdの「`branch`は依存の有無にかかわらず全issueに必須」というモデルに従う）

## グループ（Linear Project）の決め方

- `group`（Linear Project）は依頼された機能・イニシアチブ単位で1つに揃える。1つの依頼に対して複数Projectへ分散させない
- 1グループの中に複数の独立ブランチが並存してよい。グループ＝人間が確認する可視化の単位、ブランチ＝並行実装のための技術的な単位で、別軸の概念だと理解する（1グループ = 1ブランチに固定しない）
- 既存のアクティブグループ（`.linear-cli/config.json`の`project`既定値）と異なる新規グループを起票する場合でも、後述の理由により`config.json`は書き換えない

## 新規issue群はデフォルトで非アクティブのまま積む

- 各issueの`--project`引数には決定したグループ名を明示的に渡し、issue自体はそのLinear Projectに所属させる
- 一方、`.linear-cli/config.json`の`project`既定値（＝「現在アクティブなタスクグループ」）は、作成直後にはそのグループ名へ**切り替えない**。ユーザーが明示的に「このグループへ進めて」等と指示したときだけ切り替える
- 理由: 既存issueの処理中に、誤って将来グループのissueを先取りしてしまう事故を防ぐため（[00-overview.md](../../../../.claude/plans/parallel-agent-worktree-task-groups/00-overview.md)の「Project+config」方式の安全設計の要）

## Linear作成の実務: 依存順に1件ずつ

`depends_on`ヘッダには先行issueのidentifier（例: `ENG-101`）を書く必要があるため、依存グラフの根（先行issueを持たないissue）から順に`linear-cli create`を実行し、返ってきたidentifierを後続issueの`depends_on`に使う。

```bash
linear-cli create --title "<先行issueのタイトル>" --team ENG --project "<グループ名>" \
  --description "branch: my-feature-slug
base_branch: main

---
（自由記述の本文）"
# → 返り値のidentifier（例: ENG-201）を控える

linear-cli create --title "<後続issueのタイトル>" --team ENG --project "<グループ名>" \
  --description "depends_on: ENG-201
branch: my-feature-slug
base_branch: main

---
（自由記述の本文）"
```

- 構造化ヘッダの書式（フィールド名・順序・`---`区切り）は[issue-shape.md](issue-shape.md#issue-descriptionの構造化ヘッダ)に厳密に従う。**ヘッダと`---`の間の空行を忘れないこと**（無いとLinear側でSetext heading化され`---`が消える。同ファイル参照）
- ラベルは付与しない（`branch:<slug>`はdescription構造化ヘッダにのみ書く。理由は[issue-shape.md](issue-shape.md#ブランチのslug)参照）

## セルフチェック項目（Linear作成前に確認）

作成前に次の3点を満たしていることを確認する。v1では単純な直列依存のみサポートし、fan-in/fan-out（1issueが複数issueに依存する、または複数issueから依存されて分岐する）は対象外とする。

- [ ] `depends_on`の循環が無いこと
- [ ] 全issueに`branch`が設定されていること
- [ ] 同一ブランチ内で`depends_on`チェーンが分岐・合流せず一直線であること（fan-in/fan-outが無いこと）

## report後の扱い

- issue作成後、依存関係グラフ（どのissueがどれに依存し、どれが同じブランチか）をユーザーへ要約報告する
- `.linear-cli/config.json`の`project`切り替え（アクティブ化）は、この報告に対するユーザーのレビュー・明示指示を待ってから行う。配置直後に自動でアクティブ化しない
- 理由: 依存関係・ブランチ割り当ての誤りは後工程（実装中）で気づくとやり直しコストが高いため、配置直後に人間の目で確認できるようにする

## 注意点・落とし穴

- 別ブランチのissueへの`depends_on`は通常の使い方ではない（依存issueのマージ後にbase_branchを合わせる、といった運用上の工夫が別途必要になる）。分割時は同一ブランチ内でのみ`depends_on`を使うのが基本
- `linear-cli`にproject作成コマンドは無い。グループ用のLinear Projectが未作成の場合はユーザーに事前作成を依頼する
