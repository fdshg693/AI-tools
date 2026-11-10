# linear-cli スキル

## このスキルの狙い

[`tools/linear-cli/`](../../../../linear-cli/)（Node CLI、`@linear/sdk`利用）が提供するLinear操作を、エージェントが実行時に迷わず使えるよう判断フローを与える薄いラッパー。CLI本体の実装・設計判断（コマンド仕様、`.linear-cli/config.json`の探索、レート制限の扱い等）は`tools/linear-cli/README.md`側に閉じ、このスキルはSKILL.mdに書く「使い方」だけに責務を絞る（`tav-cli`と`tav-cli`スキルの分離パターンを踏襲）。

## スコープを絞った理由

このCLIが提供するのは「issue検索（ラベル絞り込み込み）」「issue作成（ラベル付与込み）」「ステータス更新（担当者割当・ラベル追加/削除込み）」「コメント追加/一覧取得/削除」「issue詳細取得」のみ。issueの削除・複数team横断の一括操作は対象外。これは[parallel-agent-worktree](../parallel-agent-worktree/)スキルがタスクキューとしてLinearを使うために必要な最小操作に絞った結果で、詳細な経緯は[.claude/plans/linear-integration/00-overview.md](../../../../.claude/plans/linear-integration/00-overview.md)を参照。

issue作成・コメント一覧取得・コメント削除は当初のスコープに含まれていなかったが、parallel-agent-worktreeが「worktree占有状況を1箇所（専用トラッキングissue）で追跡できないと空き判定が不可能」という問題を抱えたため後から追加した。トラッキングissueの検索（`search --title`）→無ければ`create`→占有時に`comment`で登録→解放時に`comment-delete`で削除、という一連の操作に必要な最小限に留めている。

ラベル絞り込み/付与/更新・`show`（issue詳細取得）は、parallel-agent-worktreeがタスクグループ（依存関係を持つ一連のissue群）に対応するために追加した。ブランチ共有ラベル（`branch:<slug>`）で「同じブランチに未完了issueが残っているか」を検索し、issue descriptionの構造化ヘッダ（`depends_on:`/`branch:`/`base_branch:`）を`show`で読む。詳細な経緯は[.claude/plans/parallel-agent-worktree-task-groups/03-linear-cli-extension.md](../../../../.claude/plans/parallel-agent-worktree-task-groups/03-linear-cli-extension.md)を参照。

## メンテナンス上の注意

`tools/linear-cli/`のCLIオプション・設定ファイル形式・挙動を変更した場合、このSKILL.mdも同じ変更の中で更新すること（自動追随しない）。
