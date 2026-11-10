---
name: parallel-agent-worktree
description: 複数のClaude Codeセッション（同一ローカル環境上で並行して動くエージェント）が、Linearの未着手issueをタスクキューとして使い、それぞれ別のgit worktreeで衝突なく1タスクずつ分担して作業を進めるためのスキル。Linear issueの検索→claim→worktree作業→完了報告までの一連の流れを自然言語指示で進めたい場合に使う。タスクグループ（Linear Project + `.linear-cli/config.json`の`project`既定値）単位でアクティブな未着手issueを絞り込み、依存関係（`depends_on`）を持つissue群は同じブランチ・worktreeを再利用しながら順番に実装する。専用のトラッキングissue1件で「どの環境がどのworktreeを使用中か」を追跡し、空き状況を判定可能にする。専用オーケストレーター（常駐プロセス等）は前提とせず、1タスクのcommit・push完了をもって処理は完結する（次のタスクへ自動で継続しない）。
# 前提条件（このスキル自体はインストール・セットアップを一切行わない）:
#   - `linear-cli` コマンドがPATH上で使え、LINEAR_API_KEYが設定済みであること
#     （セットアップは tools/_plugin/my-tools/skills/linear-cli/SKILL.md 参照）
#   - `EnterWorktree`/`ExitWorktree` がハーネス組み込みツールとして利用可能であること
#   - 対象issueが issue-shape.md の定めるタスクグループ対応版の型（構造化ヘッダ）に
#     沿って配置済みであること（起票手順は issue-authoring.md 参照）
#
# 依存スキル: tools/_plugin/my-tools/skills/linear-cli（issue検索・作成・ステータス更新・
# ラベル絞り込み/付与・コメント追加/一覧取得/削除・issue詳細取得）
# このスキルはlinear-cliとハーネス組み込みworktreeツールを繋ぐ薄いオーケストレーション層で、
# 自前のソースコードは持たない。issueの型・起票手順は同階層の issue-shape.md / issue-authoring.md
# を参照（本ファイルはそれらを前提としたオーケストレーションフローのみを扱う）。
meta:
  tag: []
  requires_repo_tools: linear-cli
  requires_env: LINEAR_API_KEY
  dependencies: none
  requires_install: none
  requires_hooks: none
  requires_skills: linear-cli
  status: experimental
  description: no description
  version: 2.0.4
---

# parallel-agent-worktree の使い方

同一ローカル環境上で複数のClaude Codeセッションを並行起動し、Linearの未着手issueをタスクキューとして分担するためのスキル。**1セッション=1タスクで完結**させる設計で、複数タスクを続けて処理したい場合はユーザーがセッションを複数起動する（このスキル自体はループしない）。

issueは[issue-shape.md](issue-shape.md)が定める型（タスクグループ=Linear Project、descriptionの構造化ヘッダ）に沿って配置されている前提。起票手順は[issue-authoring.md](issue-authoring.md)を参照。

「どの環境（PC・worktree）が今どのタスクを処理中か」は、専用の**トラッキングissue**1件に集約する。稼働中issue群のコメントを1件ずつ目視で回る必要はなく、トラッキングissueのコメント一覧を見るだけで空き状況が分かる。

## トラッキングissueのタイトル

固定文字列 `[worktree-tracking] 稼働中worktree一覧` を使う（team内で1件のみ存在する前提。複数ヒットした場合は重複なのでユーザーに知らせ、先頭の1件を使う）。

## 全体の流れ

```markdown
0. トラッキングissueの確認・作成
   linear-cli search --title "[worktree-tracking] 稼働中worktree一覧" --team <team>
   → 0件なら作成する
   linear-cli create --title "[worktree-tracking] 稼働中worktree一覧" --team <team>
   → 1件以上あれば（複数ヒットなら先頭を使う）そのidentifierを以後の手順で使い回す

1. 未着手タスクの検索（アクティブなタスクグループ内）
   linear-cli search --status <未着手を表す状態名> --assignee none
   → --project を指定しなくても、.linear-cli/config.json の project 既定値
   （＝現在アクティブなタスクグループ）で自動的に絞り込まれる（config.jsonが無い/
   project未設定なら絞り込み無しで検索される。想定と違う場合はユーザーに確認する）
   → 候補issueの一覧から着手する1件を選ぶ（複数候補があれば先頭など任意の1件でよい。
   排他制御は無いため他エージェントとの重複は許容する。「claim」節参照）

2. 依存issueの完了確認
   linear-cli show <identifier>
   → descriptionの構造化ヘッダ（depends_on: / branch: / base_branch:）を読む
   → depends_on に列挙されたissueが1つでも未完了なら、このissueは見送り、1.の候補一覧
   から別のissueへ切り替える（依存issueの完了確認は search または show でステータスを見る）。
   依存issueが無い、または全て完了済みならこのissueに着手する。見送りの判断基準・
   「待たずに次候補へ切り替える」方針の理由は「依存issueが未完了の場合」節参照

3. ブランチ解決・Worktree作成
   2.で読んだ branch:<slug> / base_branch を使い、「ブランチ解決」節の手順で
   worktreeを再利用するか新規作成するかを決め、EnterWorktree（ハーネス組み込みツール）
   で作業ディレクトリを切り替える

4. Claim（ベストエフォート）
   linear-cli update <identifier> --status <作業中を表す状態名> --assignee me@example.com
   linear-cli comment <identifier> --body "host=<PCのホスト名>, worktree=<worktreeの絶対パス>"
   linear-cli comment <トラッキングissueのidentifier> --body "host=<PCのホスト名>, worktree=<worktreeの絶対パス>, issue=<identifier>, branch=<slug>"
   → 最後のコマンドが返す comment の id を、6.の削除で使うため記憶しておく
   → いずれかのステップが失敗した場合は「claim失敗時の後始末」節に従う

5. 作業
   通常のエンジニアリング作業をworktree内で行う

6. 完了
   - Linear issueのステータスを完了を表す状態名へ更新する
     linear-cli update <identifier> --status <完了を表す状態名>
   - 変更をコミットし、push する
   - トラッキングissueから自分のエントリを削除し、占有を解放する
     linear-cli comment-delete <4.で記憶したcomment id>
   - 同じブランチに未完了issueが残っているか確認する（「完了時のブランチ残issueチェック」
     節参照）。残っていればworktreeはpush済みでもkeepし、次のissueで同じworktreeを
     再利用する前提にする
   - PRを作成するか・いつマージするかはissueの性質に応じてエージェントが判断する
     （固定ルールにしない）
   - commit・push・占有解放が終わった時点でこのスキルの処理は完了。次のissueへは
     自動で進まない（「終了・次のタスク/グループへの引き継ぎ」節参照）

7. 終了・次のタスク/グループへの引き継ぎ
   ExitWorktree はここでは能動的に呼ばない（「ExitWorktreeを能動的に呼ばない理由」節参照）。
   ユーザーが続けて同じグループ内の別issueに着手したい場合は、新しいセッションを
   開始してもらう（1.に戻れば同じアクティブグループ内から自動的に絞り込まれる）。
   グループ全体が完了し、ユーザーが次のグループへ進めるよう明示指示した場合のみ
   「次タスクグループへの切り替え」節の手順を行う
```

## 依存issueが未完了の場合

- 依存issue（`depends_on`）が1件でも未完了の場合、そのissueには着手せず、検索結果の別候補へ切り替える。依存issueの完了を**待機しない**
- 理由: このスキルは「claimはベストエフォート・厳密な排他制御なし」「1セッション=1タスクで完結」という自律境界を前提にしている。依存待ちのブロッキングを許すとこの前提が崩れるため、「今すぐ着手できるものを選ぶ」挙動に統一する
- 見送れる候補が無い（依存issueが全て未完了で他に候補も無い）場合は、その旨をユーザーに報告する

## ブランチ解決

「3. ブランチ解決・Worktree作成」で使う手順。`show`で読んだ`branch:<slug>`（必須）と`base_branch`（省略時はリポジトリのdefaultブランチ）をもとに、`git worktree list`の結果を正として次の3パターンのいずれかを選ぶ。

1. **既存worktreeを再利用する** — `<slug>`を含むブランチのworktreeが既に`git worktree list`に存在する場合。再利用前に、トラッキングissueのコメント一覧（「環境不足の可視化」節）を確認し、そのbranch/worktreeが現在他セッションに占有されていないことを再確認する（`git worktree list`はディスク上の存在有無しか分からず、「今まさに別セッションが作業中か」は分からないため）。占有されていなければ`EnterWorktree({ path: <既存worktreeの絶対パス> })`でアタッチする
2. **新規worktreeを作る（主経路）** — 該当worktreeが存在せず、`base_branch`がリポジトリのdefaultブランチと同じ（または省略）場合。`EnterWorktree({ name: "<slug>"を含む名前 })`で新規作成する
3. **新規worktreeを作る（base_branchがdefaultと異なる場合）** — 該当worktreeが存在せず、`base_branch`がdefaultと異なる場合。`git worktree add <path> -b <slug> <base_branch>`で手動作成した後、`EnterWorktree({ path: <path> })`でアタッチする

パターン3が必要な理由: `EnterWorktree({ name })`は呼び出し単位でbase refを指定できず、base refは`worktree.baseRef`というリポジトリ全体の設定で決まる（`fresh`＝既定ではorigin/デフォルトブランチ、`head`＝現在のローカルHEAD）。issueごとに`worktree.baseRef`を切り替えると同時に動く他セッションに影響するため、切り替えは行わない。`EnterWorktree`の`path`引数は「`git worktree add`で作った既存worktreeへの後からのアタッチ」を明示的にサポートしており、この経路で回避する。

パターン1・3で使う`EnterWorktree({ path })`は、まだこのセッションで一度もworktreeに入っていない状態であれば`name`によるworktree作成と同様に使える（`EnterWorktree`は「既に別のworktreeセッションに入っている状態からの`name`新規作成」だけを禁止しており、`path`によるアタッチは制約が別）。1セッション=1タスクの設計上、通常はこの手順の最初の1回しかworktreeへ入らない。

## Claim（ベストエフォート）

- 未着手→作業中の更新に、更新前後の厳密な排他制御（比較更新・楽観ロック）は行わない。まれに複数エージェントが同じissueを二重にclaimすることを許容する。二重着手に気づいた側は担当者/ステータスを見直し、別のissueへ切り替える運用でカバーする
- 環境情報コメント（`host=..., worktree=...`）は、claim時にタスクissue・トラッキングissueの両方へ1回ずつ投稿する。タスクissue側は履歴として残し続ける（削除しない）。トラッキングissue側は完了時に`comment-delete`で消し、現在の占有状況だけが残る設計

## claim失敗時の後始末

「4. Claim」の3コマンド（ステータス更新・タスクissueへのコメント・トラッキングissueへのコメント）のいずれかがAPIエラー等で失敗した場合、「worktreeだけ作って誰にも紐づかない」状態や「占有記録に失敗したまま作業を進める」状態を残さないため、作成したworktreeを `ExitWorktree({ action: "remove" })` で削除してから作業を中断する。まだコミットしていない段階なので `discard_changes` は不要なはずだが、エラーで停止して残っている場合は内容を確認してから判断する。それまでに成功していたコマンド（例: ステータス更新のみ成功しコメントが失敗した）があれば、可能な範囲で状態を巻き戻す（ステータスを元に戻す等）か、失敗内容をユーザーに報告して判断を仰ぐ。

## 完了時のブランチ残issueチェック

「6. 完了」では、Linearラベルではなく現在のタスクグループ（`--project`）内の全issueをdescription構造化ヘッダの`branch:`フィールドで照合して判定する（ラベルを使わない理由は[issue-shape.md](issue-shape.md#ブランチのslug)参照）。

```bash
linear-cli search --project "<現在のグループ名>" --json
```

→ 返ってきた各issue（自分自身を除く）について `linear-cli show <identifier>` でdescriptionを読み、構造化ヘッダの`branch:`が自分と同じslugかを確認する。完了扱いのステータスを除いて該当issueが残っているかをエージェント側で判定する（タスクグループ内のissue数は小規模な想定のため、この総当たりで足りる。CLI側にdescription内容でのフィルタは無い）。

- 残っている場合: そのブランチ上でまだ後続issueが実装される見込みがあるため、worktreeはpush済みでも`keep`する（次のissueのセッションが同じworktreeを「ブランチ解決」節のパターン1で再利用できるようにする）
- 残っていない場合: 従来通り、push済みなら`remove`してよい（「ExitWorktreeを能動的に呼ばない理由」節の判断基準に従う）

## ExitWorktreeを能動的に呼ばない理由

`ExitWorktree` ツール自体の説明文は「Do NOT call this proactively — only when the user asks」と明記しており、`EnterWorktree` にある「プロジェクト指示（CLAUDE.md/memory等）による起動なら明示指示として扱ってよい」という例外が無い。そのため、このスキルはタスク完了（6. 完了）後に自動で `ExitWorktree` を呼ばない。

- ユーザーが明示的に「worktreeを閉じて」「元のディレクトリに戻って」等と指示した場合のみ `ExitWorktree` を呼ぶ。判断基準は次の通り:
  - 6.で確認した「同じブランチに未完了issueが残っているか」で残っている → `action: "keep"`（次のissueが同じworktreeを再利用するため。push済みでもこの条件が優先される。詳細は「完了時のブランチ残issueチェック」節参照）
  - 残っておらず、push済み（コミットがリモートに存在する）→ `action: "remove"`（手元のworktreeを消しても作業は失われない。空きworktreeを増やして次のタスクに使い回せる）
  - 残っておらず、未pushの差分が残っている → `action: "keep"`
- ユーザーが何も指示しない場合は、セッション終了時のharness標準動作（keep/remove確認プロンプト）にそのまま委ねる

## 環境不足の可視化

```bash
linear-cli comments <トラッキングissueのidentifier>
```

このコマンド1回で、現在どの環境（PC・worktree絶対パス）がどのissueを処理中かの一覧が得られる（各コメントが1エントリ）。新しいworktreeを作るかどうかの判断は、この一覧をもとに人間またはエージェントが行う（空き状況の自動判定ロジックはこのスキルのスコープ外）。

- エントリが残ったまま完了操作（6.）が行われなかった場合（エージェントのクラッシュ等）、そのエントリは占有中として残り続ける。自動的な期限切れ処理は無いため、明らかに古い・対応するworktreeが実在しないエントリを見つけた場合は`comment-delete`で手動削除するか、ユーザーに確認する

## 次タスクグループへの切り替え

「現在アクティブなタスクグループ」＝`.linear-cli/config.json`の`project`既定値を次のグループのProject名へ書き換え、commitする操作。git diffとして残るため、いつ・どのグループへ切り替えたかが監査可能になる（[issue-shape.md](issue-shape.md)参照）。

- **ユーザーの明示指示がある場合のみ**エージェントが実行する（「次のグループへ進めて」等）。グループが完了したように見えても、この節の操作を自動で・先回りして行わない
- 手順:
  1. 現在のグループに未完了issueが残っていないかを`linear-cli search --project "<現在のグループ名>"`等で確認し、ユーザーへ結果を共有する
  2. `.linear-cli/config.json`の`project`値を次のグループのProject名に書き換える
  3. 変更をcommitする
- 次のグループのissue群は、[issue-authoring.md](issue-authoring.md)の手順で既にLinearへ配置済みだが`config.json`は書き換えられていない状態（＝非アクティブなまま積まれている）のはずである。この節の操作がその配置後のアクティブ化に相当する
- 複数タスクグループを同時にアクティブにする運用はサポートしない（逐次進行のみ）

## 注意点

- `EnterWorktree` は「既に別のworktreeセッションに入っている状態から `name` で新規作成」できない。1セッション=1タスクで完結させる設計上、通常はこの制約に触れない
- ワークフロー状態名（「未着手」「作業中」「完了」に相当する名前）はチームのLinear設定次第で異なる。ハードコードせず、`linear-cli search` を状態名なしで実行するかユーザーに確認して実際の状態名を把握する（`linear-cli` スキル参照）
- トラッキングissueのteamは、`.linear-cli/config.json`に既定値が無ければ`--team`を毎回指定する必要がある。不明な場合はユーザーに確認する
- `linear-cli` のインストール・`LINEAR_API_KEY` 設定はこのスキルでは行わない。未設定エラーが出た場合は `tools/_plugin/my-tools/skills/linear-cli/SKILL.md` の案内に従う
- 複数タスクグループの同時並行進行は非対応。`.linear-cli/config.json`の`project`はユーザーが明示指示するまで変更しない（「次タスクグループへの切り替え」節参照）
- `depends_on`はv1では単純な直列依存のみ想定（fan-in/fan-outは非対応）。想定外の依存構造のissueに遭遇した場合はユーザーに確認する（[issue-authoring.md](issue-authoring.md)の「セルフチェック項目」参照）
