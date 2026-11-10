# parallel-agent-worktree スキル

## このスキルの狙い

同一ローカル環境上で複数のClaude Codeセッションを並行起動し、Linearの未着手issueをタスクキューとして衝突なく分担するための「使い方」を与える薄いオーケストレーション層。専用の常駐オーケストレータープロセスは作らず、各セッションが自然言語のSKILL.md指示に従って自律的に「検索→worktree作成→claim→作業→完了報告」を行う設計（初期実装の詳細な経緯・検討過程は[.claude/plans/parallel-agent-worktree-task-groups/00-overview.md](../../../../.claude/plans/parallel-agent-worktree-task-groups/00-overview.md)参照）。

対象issueの型（タスクグループ・依存関係・ブランチ共有）は[issue-shape.md](issue-shape.md)が、issue起票の手順は[issue-authoring.md](issue-authoring.md)が定める。タスクグループ対応（ブランチ共有・依存関係・worktree再利用）の設計意図は本ファイルの「タスクグループ・依存関係・worktree再利用に対応した経緯」節を参照。

このスキル自体はソースコードを持たず、[linear-cli](../linear-cli/)（Linear操作）とハーネス組み込みの`EnterWorktree`/`ExitWorktree`（worktree管理）を繋ぐ判断フローだけを提供する。

## 1セッション=1タスクで完結させる理由

当初案では「1タスク完了ごとに`ExitWorktree`して次のタスクへ進む」自律ループを想定していたが、実装時に`ExitWorktree`ツール自体の説明文が「Do NOT call this proactively — only when the user asks」と明記していることが判明した。`EnterWorktree`にある「プロジェクト指示（CLAUDE.md/memory等）による起動なら明示指示として扱ってよい」という例外が`ExitWorktree`側には無く、字面通りに読むとタスク完了ごとの自動`ExitWorktree`呼び出しはツールの想定用途から外れる。

ユーザー確認の結果、「1タスクのcommit・pushをもって処理は完結し、続けて別タスクに着手したい場合はユーザーが新しいセッションを起動する」という運用に倒すことでこの制約と両立させた。そのため`ExitWorktree`はSKILL.mdからは能動的に呼ばず、ユーザーが明示的に要求した場合、またはharness標準のセッション終了時keep/remove確認に委ねる。

## トラッキングissue方式に変更した経緯

当初案は「稼働中（ステータス=作業中）issue群それぞれに付いた環境コメントを人間が目視で回って空き状況を把握する」設計だった。実装後にユーザーから「これでは空きworktreeの判定が事実上不可能」との指摘を受けた。理由は2点:

1. **解放シグナルが無い** — タスク完了時にissueのステータスは変わるが、環境コメント自体は削除されず、コメントだけを見ても「まだ稼働中か」を判断できない
2. **1箇所に集約されていない** — タスクissueの数だけ分散するため、空き状況を知るには稼働中issueを1件ずつ開いて回る必要がある

これを解消するため、専用の**トラッキングissue1件**に環境エントリを集約する方式に変更した。claim時にエントリを`comment`で追加し、完了時に同じエントリを`comment-delete`で削除することで、トラッキングissueのコメント一覧＝現在の占有状況そのものになる（[linear-cli](../linear-cli/)側に`create`/`comments`/`comment-delete`を追加実装。詳細は[linear-cli README](../linear-cli/README.md)の「スコープを絞った理由」節参照）。

この方式にも限界はある。エージェントがクラッシュする等で完了操作（SKILL.mdの「6. 完了」）を踏まずに終わった場合、そのエントリは占有中のまま残り続ける（自動失効なし）。ベストエフォート運用（claimの排他制御と同じ思想）として許容し、明らかに古いエントリは人間またはエージェントが目視で気づいて手動削除する運用にした。

## タスクグループ・依存関係・worktree再利用に対応した経緯

当初は「1 issue = 1 worktree」固定で、依存関係のある一連のissueを同じブランチ上で順番に実装する手段が無く、issueを消化するたびにworktreeが増え続ける（乱立する）問題があった。ユーザー要望を受け、①どのISSUE群（タスクグループ）に取り組んでいるかを可視化し、グループ完了・ユーザー確認後に次グループへ進められる仕組み、②issueが依存関係と作業ブランチを明示し、同じブランチ上で関連issueを順番に実装できる仕組み、の2点を追加した（検討過程は[.claude/plans/parallel-agent-worktree-task-groups/00-overview.md](../../../../.claude/plans/parallel-agent-worktree-task-groups/00-overview.md)参照）。対象は「このスキル専用の型を持つISSUE」に限定し、汎用issue全般との後方互換は考慮していない。

### なぜ「ラベル」でなく「Linear Project + `.linear-cli/config.json`」でタスクグループを表すか

ユーザーからの要望原文は「ラベル」だったが、実装時に意図的に逸脱した。`linear-cli search`/`create`は元々`--project`引数を持っており、コード変更ゼロで「現在アクティブなグループ」の絞り込みができる。加えて`config.json`はリポジトリにコミットされるため、グループ切り替え（次タスクグループへ進める操作）がgit diffとして残り監査可能になる。一方「ブランチ」（同じブランチで直列実装するissue群の単位）はLinearにProject以上に細かいnativeグルーピングが無いため、こちらはdescription構造化ヘッダの`branch:<slug>`フィールドで表現する。当初はこの`branch:`をLinearラベルとしても付与していたが、ラベル値はslugを切るたび（＝タスクグループを起票するたび）にLinear UI側での事前登録という手動作業を要求し、`linear-cli`もtypoによるラベル乱立防止のため自動作成を意図的にサポートしていない（`tools/linear-cli/src/labels.mjs`参照）ことから、起票のたびに人手が挟まる運用コストに見合わないと判断し廃止した。両者の役割分担は[issue-shape.md](issue-shape.md)参照。

### なぜ`git worktree list`をworktree再利用可否の正とするか

worktreeはホストローカルなファイルシステム状態であり、Linear側のテキスト（トラッキングissueのコメント等）を正にすると乖離（stale化）するリスクがある。そのため「そのブランチのworktreeが存在するか」の判定は必ずホスト上の`git worktree list`で行う。トラッキングissueは「今どこが稼働中か」という占有チェック（衝突防止のための最終確認）専用に留め、再利用可否そのものの判定には使わない（[SKILL.md](SKILL.md)の「ブランチ解決」節参照）。

### 依存先issue・ベースブランチをdescriptionの構造化ヘッダで表現する理由

Linear純正のissue relations APIは使わず、`depends_on:`/`branch:`/`base_branch:`をSKILL.mdのfrontmatterと同じ見た目でissue descriptionの冒頭に書く方式にした。relations APIはSDK側の対応状況の裏取りが別途必要で実装コストが高く、依存先は1〜2件程度に留まる想定のため、`show`コマンド（Linear側実装拡張）で都度読めば十分と判断した。

### ベースブランチがdefaultと異なる場合に`EnterWorktree`の`baseRef`設定を切り替えない理由

`EnterWorktree`は呼び出し単位でbase refを指定できず、base refは`worktree.baseRef`というリポジトリ全体設定で決まる。issueごとに切り替えると同時に動く他セッションに影響するため、この設定は変更しない。代わりに`base_branch`がdefaultと異なる場合のみ`git worktree add`で手動作成し、`EnterWorktree({ path })`（既存worktreeへの後からのアタッチをサポートする引数）でアタッチする経路に統一した（[SKILL.md](SKILL.md)の「ブランチ解決」節参照）。

## スコープ外・意図的に持たない機能

- **claimの厳密な排他制御** — 比較更新・楽観ロックは持たない（ベストエフォート、ユーザー確認済み）。`linear-cli`側も同じ方針（[linear-cli README](../linear-cli/README.md)参照）
- **占有エントリの自動失効・自動クリーンアップ** — クラッシュ等で残った古いエントリの検出は人手に委ねる（上記「トラッキングissue方式に変更した経緯」参照）
- **PR作成・マージタイミングの固定ルール化** — issueごとにエージェントが判断する
- **複数タスクグループの同時並行進行** — 逐次進行のみサポート（[issue-shape.md](issue-shape.md)参照）
- **依存issue完了までのブロッキング待機** — 依存未完了issueは待たずに見送り、別候補へ切り替える（[SKILL.md](SKILL.md)の「依存issueが未完了の場合」節参照）
- **fan-in/fan-out（分岐・合流する依存関係）** — v1では単純な直列依存のみサポート（[issue-authoring.md](issue-authoring.md)参照）

## メンテナンス上の注意

- `EnterWorktree`/`ExitWorktree`ツールの説明文（挙動・制約）が変わった場合、SKILL.mdの該当節（特に「ExitWorktreeを能動的に呼ばない理由」「ブランチ解決」）を合わせて見直すこと（自動追随しない）
- `linear-cli`側のサブコマンド・オプションが変わった場合も、このSKILL.mdの記載例が古くならないよう確認すること
- トラッキングissueのタイトル文字列（`[worktree-tracking] 稼働中worktree一覧`）を変更する場合、SKILL.md本文の全箇所を揃えて更新すること（検索・作成の両方で同じ文字列を使うため、片方だけ変えると新規作成が乱立する）
- `issue-shape.md`のフィールド名・書式（`depends_on:`/`branch:`/`base_branch:`）を変更する場合、`issue-authoring.md`とSKILL.mdの記載例（構造化ヘッダの読み方・完了時のブランチ残issueチェックの実装）を合わせて更新すること
