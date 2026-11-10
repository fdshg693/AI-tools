/** issueへのMarkdownコメント追加（環境記録・完了報告用）。 */
export async function addComment(client, issueId, body) {
  const payload = await client.createComment({ issueId, body });
  const comment = await payload.comment;

  return { success: payload.success, id: comment?.id ?? null, url: comment?.url ?? null };
}

/** issueに付いたコメント一覧を取得する（環境占有状況の可視化用）。 */
export async function listComments(client, issueId) {
  const issue = await client.issue(issueId);
  const connection = await issue.comments({ first: 100 });

  return connection.nodes.map((comment) => ({
    id: comment.id,
    body: comment.body,
    createdAt: comment.createdAt,
    url: comment.url,
  }));
}

/** コメントを削除する（環境占有解除用）。issueIdは不要（コメントIDはグローバルに一意）。 */
export async function deleteComment(client, commentId) {
  const payload = await client.deleteComment(commentId);
  return { success: payload.success };
}
