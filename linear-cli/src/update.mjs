import { resolveLabelIds } from "./labels.mjs";

/**
 * issueのワークフロー状態遷移・担当者割当・ラベル追加/削除・description全文置換。stateはステータス名から
 * teamスコープでworkflowStatesクエリにより解決する（状態名をハードコードせず、チーム独自カスタマイズにも
 * 追随する）。assignee には "none" を指定すると担当者を外す。
 * addLabels/removeLabelsは現在の`issue.labelIds`を読み取り→追加/削除を計算→全体を送り直す
 * read-modify-write方式（比較更新・楽観ロックは行わない。既存のclaimと同じベストエフォート方針）。
 * descriptionは部分編集ではなく全文置換（Linear APIに部分パッチ手段は無い）。
 */
export async function updateIssue(
  client,
  issueId,
  { status, assignee, addLabels, removeLabels, description },
) {
  if (
    !status &&
    assignee === undefined &&
    !addLabels?.length &&
    !removeLabels?.length &&
    description === undefined
  ) {
    throw new Error(
      "--status / --assignee / --add-label / --remove-label / --description のいずれかを指定してください。",
    );
  }

  const issue = await client.issue(issueId);
  const input = {};

  if (description !== undefined) {
    input.description = description;
  }

  if (status) {
    const team = await issue.team;
    const states = await client.workflowStates({
      filter: { name: { eq: status }, team: { id: { eq: team.id } } },
    });
    const state = states.nodes[0];
    if (!state) {
      throw new Error(`チーム "${team.key}" にステータス "${status}" は存在しません。`);
    }
    input.stateId = state.id;
  }

  if (assignee === "none") {
    input.assigneeId = null;
  } else if (assignee) {
    const users = await client.users({ filter: { email: { eq: assignee } } });
    const user = users.nodes[0];
    if (!user) {
      throw new Error(`メールアドレス "${assignee}" のユーザーが見つかりません。`);
    }
    input.assigneeId = user.id;
  }

  if (addLabels?.length || removeLabels?.length) {
    const team = await issue.team;
    const [addIds, removeIds] = await Promise.all([
      addLabels?.length ? resolveLabelIds(client, team.id, addLabels) : [],
      removeLabels?.length ? resolveLabelIds(client, team.id, removeLabels) : [],
    ]);
    const removeSet = new Set(removeIds);
    const next = new Set(issue.labelIds.filter((id) => !removeSet.has(id)));
    for (const id of addIds) next.add(id);
    input.labelIds = [...next];
  }

  const payload = await client.updateIssue(issueId, input);
  const updated = await payload.issue;

  return { identifier: updated?.identifier ?? issueId, success: payload.success };
}
