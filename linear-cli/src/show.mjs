/**
 * 単一issueの詳細取得。description本文を含むため、一覧用のsearchとは別コマンドとして独立させる
 * （parallel-agent-worktreeが依存先issue・ブランチ情報をdescriptionヘッダから読むために使う）。
 */
export async function getIssue(client, identifier) {
  const issue = await client.issue(identifier);

  const [state, assignee, project, labelConnection] = await Promise.all([
    issue.state,
    issue.assignee,
    issue.project,
    issue.labels(),
  ]);

  return {
    identifier: issue.identifier,
    title: issue.title,
    description: issue.description ?? null,
    status: state?.name ?? null,
    assignee: assignee?.email ?? null,
    project: project?.name ?? null,
    labels: labelConnection.nodes.map((label) => label.name),
    url: issue.url,
  };
}
