/**
 * ラベル名（複数可）をteam-scopedで`client.issueLabels`からIDへ解決する。
 * 存在しないラベル名が1つでもあればエラー終了する（`update.mjs`のワークフロー状態解決と同じ思想。
 * ラベルの新設はLinear UI側で人間が行う運用とし、typoによるラベル乱立を防ぐ）。
 */
export async function resolveLabelIds(client, teamId, names) {
  return Promise.all(
    names.map(async (name) => {
      const labels = await client.issueLabels({
        filter: { name: { eq: name }, team: { id: { eq: teamId } } },
      });
      const label = labels.nodes[0];
      if (!label) {
        throw new Error(`チームにラベル "${name}" は存在しません。`);
      }
      return label.id;
    }),
  );
}
