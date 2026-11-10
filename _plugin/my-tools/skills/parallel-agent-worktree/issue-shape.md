# issue-shape — タスクグループ対応版ISSUEの型とLinear/linear-cli設定

このファイルは[parallel-agent-worktree](SKILL.md)がタスクグループ（依存関係を持つ一連のissue群）に対応するために、ISSUE側が満たすべき型と、それを支えるLinear/`linear-cli`側の設定をまとめる。[02-issue-authoring-procedure](../../../../.claude/plans/parallel-agent-worktree-task-groups/02-issue-authoring-procedure.md)（AI向け手順書）・[03-linear-cli-extension](../../../../.claude/plans/parallel-agent-worktree-task-groups/03-linear-cli-extension.md)（CLI拡張）・[04-skill-rewrite](../../../../.claude/plans/parallel-agent-worktree-task-groups/04-skill-rewrite.md)（スキル本体書き換え）はこのファイルが定める仕様を前提に進める。

対象は「このスキル専用の型を持つISSUE」に限定する。汎用issue全般との後方互換は考慮しない。

## タスクグループ = Linear Project

- 1タスクグループ = 1 Linear Project。Projectはこのファイルが定める仕組みの対象外（`linear-cli`にproject作成コマンドは無いため、Linear UI側で事前に作成しておく）
- 「現在アクティブなタスクグループ」は、リポジトリルートの`.linear-cli/config.json`（[linear-cliスキル](../linear-cli/SKILL.md)参照）の`project`既定値**1つ**で表す。複数タスクグループを同時にアクティブにする運用はサポートしない（逐次進行のみ）
- 次のタスクグループへ進める操作 = `config.json`の`project`値を次のProject名に書き換えてcommitする操作そのもの。git diffとして残るため、いつ・どのグループへ切り替えたかが監査可能
- `search`/`create`は既に`--project`引数を持つため、コード変更なしで「アクティブなグループに属するissueだけを見る」絞り込みができる（`--project`未指定時は設定ファイルの既定値が使われる）

## ブランチのslug

- 同じブランチ上で順番に実装するissue群は、description構造化ヘッダの`branch:<slug>`フィールド（後述）を共通の値にする
- `slug`はgitブランチ名の一部としてそのまま使われるため、**小文字英数字とハイフンのみ**（正規表現でいう`^[a-z0-9-]+$`）に制限する
- 「同じブランチに未完了issueが残っているか」は、Linearラベルではなく`--project`スコープの総当たり（`search --project`→各issueを`show`してヘッダの`branch:`を照合）で判定する（[SKILL.md](SKILL.md)の「完了時のブランチ残issueチェック」節参照）。当初はLinearラベル`branch:<slug>`も併用する設計だったが、ラベル値はslugを切るたび（＝タスクグループを起票するたび）にteam側へ事前登録するLinear UI手動作業を要求し、起票のたびに人手が挟まる運用コストが見合わないため廃止した。ラベルの新設自体は`linear-cli`が意図的にサポートしていない（typoによるラベル乱立防止のための設計。`tools/linear-cli/src/labels.mjs`参照）ため、この情報はもともとdescription構造化ヘッダ側にしかない一次情報であり、ラベル側は単なる重複インデックスに過ぎなかった
- worktree再利用の可否そのものはラベルやヘッダではなくホスト上の`git worktree list`を正とする（[00-overview.md](../../../../.claude/plans/parallel-agent-worktree-task-groups/00-overview.md)の決定事項）

## Issue descriptionの構造化ヘッダ

すべてのissueのdescription冒頭に、SKILL.mdのfrontmatterと同じ見た目の構造化ヘッダを置き、`---`区切りの後に自由記述の本文を続ける。

```
depends_on: ENG-101, ENG-102
branch: my-feature-slug
base_branch: main

---
（自由記述の本文。通常のissue descriptionと同じ）
```

ヘッダの3フィールドと`---`の間には**必ず空行を1行入れる**こと。空行を入れずヘッダの直後に`---`を続けると、Linear側でdescriptionがMarkdownとして解釈・再シリアライズされる際にヘッダ部分がSetext heading（`見出し\n---`という書式）として吸収され、`---`自体が消えてしまう（`linear-cli create`/`update`で実際に検証済みの挙動）。空行を挟めば`---`は独立した thematic break として保存され、ヘッダと本文の区切りが保たれる。

| フィールド    | 必須     | 説明                                                                                                                                       |
| ------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `depends_on`  | 省略可   | 先行issueのidentifierをカンマ区切りで列挙。このissueに着手する前に完了しているべきissue群。依存が無ければ行ごと省略する                    |
| `branch`      | **必須** | 作業ブランチのslug。依存の有無にかかわらず全issueに必須（単発issueも「自分専用の1issueだけのブランチ」を持つ、という一貫したモデルにする） |
| `base_branch` | 省略可   | 依存グループの先頭issueが最初にworktree/ブランチを作る際の起点ブランチ。省略時はリポジトリのdefaultブランチ                                |

Linear純正のissue relations APIは使わない（SDK側の対応状況の裏取りコストに見合わないほど依存先が少ないため）。依存先の確認は、Step3で追加する`show`コマンドでdescriptionを都度読むことで足りる。

### `base_branch`を明示指定する場合の注意

`base_branch`がリポジトリのdefaultブランチと同じ場合のみが主経路（このケースは`EnterWorktree({ name })`だけで完結する）。それ以外の値を指定する運用も書式上は許すが、[04-skill-rewrite](../../../../.claude/plans/parallel-agent-worktree-task-groups/04-skill-rewrite.md)側で「`git worktree add`で手動作成 → `EnterWorktree({ path })`でアタッチ」という追加手順が必要になる。`EnterWorktree`は呼び出し単位でbase refを指定できず、`worktree.baseRef`設定はリポジトリ全体に影響するため切り替えない、という制約による（[00-overview.md](../../../../.claude/plans/parallel-agent-worktree-task-groups/00-overview.md)参照）。issueを書く時点でこのコストを把握できるよう、ここに明記する。

## トラッキングissueコメント書式の拡張

既存の占有コメント書式（[SKILL.md](SKILL.md)の「3. Claim」参照）に`branch=<slug>`を追記する。

```
host=<PCのホスト名>, worktree=<worktreeの絶対パス>, issue=<identifier>, branch=<slug>
```

追記の目的は人間が一覧を見たときの可読性向上のみ。worktree再利用の可否判定の正はあくまでホスト上の`git worktree list`であり、このコメントはそれを裏付ける表示用の情報に留まる。

## 注意点・落とし穴

- 複数タスクグループの同時並行進行は非対応。ユーザーが「次のグループへ進めたい」と言うまでは`config.json`の`project`を変更しない
- `depends_on`で参照するidentifierは、実在し・同じ`branch`を共有しているのが通常の使い方（別ブランチのissueへの依存は、その依存issueのマージ後にbase_branchを合わせる、といった運用上の工夫が別途必要になる。このファイルではその詳細までは規定しない）
