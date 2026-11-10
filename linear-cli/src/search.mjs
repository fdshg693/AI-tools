/**
 * issue検索。team/project/status/assignee/title/labelの各絞り込みは指定された分だけfilterに載る
 * （すべて未指定ならフィルタ無しでAPIキーがアクセス可能な全issueを対象にする）。
 * assignee には "none" を指定すると未アサインissueに絞り込む。titleは完全一致。
 * labelはID解決せずラベル名をそのままfilterへ渡す（state/titleと同じ既存パターン）。
 */
export async function searchIssues(
  client,
  { team, project, status, assignee, title, label, limit },
) {
  const filter = {};
  if (team) filter.team = { key: { eq: team } };
  if (project) filter.project = { name: { eq: project } };
  if (status) filter.state = { name: { eq: status } };
  if (title) filter.title = { eq: title };
  if (label) filter.labels = { name: { eq: label } };
  if (assignee === "none") {
    filter.assignee = { null: true };
  } else if (assignee) {
    filter.assignee = { email: { eq: assignee } };
  }

  const connection = await client.issues({ filter, first: limit });

  return Promise.all(
    connection.nodes.map(async (issue) => {
      const [state, assigneeUser] = await Promise.all([issue.state, issue.assignee]);
      return {
        identifier: issue.identifier,
        title: issue.title,
        status: state?.name ?? null,
        assignee: assigneeUser?.email ?? null,
        url: issue.url,
      };
    }),
  );
}
