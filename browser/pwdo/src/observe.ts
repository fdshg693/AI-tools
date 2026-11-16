import { assertAllowedCommand, runCli, type CliLauncher, type RunOptions } from './passthrough.js';
import { errorText, parseOutput, parsePageSection, type PageInfo } from './parse.js';

/**
 * 観測と操作の層。実行層（passthrough.ts）を包んで、stdout を構造化する。
 *
 * 分担:
 *  - **観測**（`observe` / `find`）は `pwq` 越しに撃つ。ダイジェストで長さが上限付きになるため
 *  - **操作**（click / fill / …）は `playwright-cli` を直に撃つ。pwq を挟む意味が無く、
 *    アクションの出力は短いので横取りも要らない
 *
 * ここは **モデルに見せる文字列を組み立てる最後の場所**でもある。
 * ストアのパスや `pwq cache show` の案内はモデルには渡さない（全文を読む経路を持たせないため）。
 */

export interface ObserveResult {
  /** モデルに見せる本文（ダイジェスト） */
  text: string;
  page: PageInfo;
}

export interface ActionResult {
  ok: boolean;
  /** モデルに見せる本文。成功なら 1〜2 行、失敗ならエラー文 */
  text: string;
  page: PageInfo;
  /** playwright-cli が出した「実行された Playwright コード」。ログの材料にはしない（回収は script.ts） */
  ranCode?: string;
  /**
   * 実行層が撃った playwright-cli コマンド（`fill` の値は伏せてある）と終了コード。
   *
   * **失敗理由をモデルの自己申告だけに頼らないため**に持つ。返却物では
   * `lastError`（機械的な事実）としてモデルの `summary` とは別の場所に置く。
   */
  command: string;
  exitCode: number;
}

export interface OperationContext {
  playwright: CliLauncher;
  pwq: CliLauncher;
  session: string;
  run: RunOptions;
}

/**
 * pwq のダイジェストからストア由来の行を落とす。
 *
 * `- cached:` / `- file:` / `- raw:` はキャッシュの在り処と全文の読み方で、
 * **モデルには渡さない**（`pwq cache show` を配線しない決定と揃える。一撃で入力トークンが跳ねる）。
 * 末尾の untrusted 注記も落とす — 同じ趣旨の宣言はシステムプロンプト側で一度だけ行う。
 */
export function stripStoreLines(text: string): string {
  return text
    .split('\n')
    .filter(line => !/^- (?:cached|file|raw):/.test(line))
    .filter(line => !line.startsWith('> [pwq]'))
    .filter(line => !/^\(pwq: cached as /.test(line))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/**
 * pwq を撃つときの共通オプション。
 *
 * `--pwq-threshold=0` が肝。既定の pwq は小さい snapshot を素通しするので、
 * ページの大きさによってモデルが受け取る形（生 YAML / ref 表）が変わってしまう。
 * 0 にすると常にダイジェストになり、**1 ステップの入力量に上限が付く**。
 * `--json` / `--raw` は付けない（付けると pwq が横取りをやめて素通しする）。
 */
function pwqArgs(session: string, rest: string[]): string[] {
  return ['--pwq-threshold=0', `-s=${session}`, ...rest];
}

export async function observe(ctx: OperationContext): Promise<ObserveResult> {
  const result = await runCli(ctx.pwq, pwqArgs(ctx.session, ['snapshot']), ctx.run);
  const parsed = parseOutput(result.stdout);
  const error = errorText(parsed);
  if (error)
    throw new ObserveError(error);
  if (result.timedOut)
    throw new ObserveError(`snapshot が ${Math.round(ctx.run.timeoutMs / 1000)} 秒で終わりませんでした`);
  if (result.code !== 0 && !result.stdout.trim())
    throw new ObserveError(result.stderr.trim() || `pwq snapshot が終了コード ${result.code} を返しました`);
  return { text: stripStoreLines(result.stdout), page: parsePageSection(parsed) };
}

export async function find(ctx: OperationContext, text: string): Promise<ObserveResult> {
  const result = await runCli(ctx.pwq, pwqArgs(ctx.session, ['find', text]), ctx.run);
  const parsed = parseOutput(result.stdout);
  const error = errorText(parsed);
  if (error)
    throw new ObserveError(error);
  if (result.timedOut)
    throw new ObserveError(`find が ${Math.round(ctx.run.timeoutMs / 1000)} 秒で終わりませんでした`);
  return { text: stripStoreLines(result.stdout), page: parsePageSection(parsed) };
}

export class ObserveError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ObserveError';
  }
}

/**
 * 返却物に載せる playwright-cli コマンドの綴り。
 *
 * **`fill` の値だけは伏せる。** ここは失敗時に `lastError.command` として呼び出し側の会話へ出る経路で、
 * 操作ログ（`fill: … ← 14 文字`）で長さしか出さないと決めたのと同じ線を引く。
 * 伏せずに素通しすると、住所やメールが「デバッグ情報」の顔をして返却物に入る。
 */
export function redactCommand(args: string[]): string {
  if (args[0] !== 'fill' || args.length < 3)
    return args.join(' ');
  const masked = [...args];
  masked[2] = `<${[...args[2]].length} 文字>`;
  return masked.join(' ');
}

/**
 * 現在地だけを取りに行く。**本文は捨てる。**
 *
 * 失敗・中断で終わった走行でも「最終 URL」を返却物に入れるための最後の手段で、
 * 呼び出し側がブラウザを見に行かずに次の一手を決められること（Step3 の主眼）を担保する。
 * 失敗しても投げない —— 復帰情報を集めるための呼び出しが、復帰情報を壊してはいけない。
 */
export async function probePageInfo(ctx: OperationContext): Promise<{ page: PageInfo; text: string } | undefined> {
  try {
    const result = await runCli(ctx.pwq, pwqArgs(ctx.session, ['snapshot']), ctx.run);
    const parsed = parseOutput(result.stdout);
    if (errorText(parsed))
      return undefined;
    return { page: parsePageSection(parsed), text: result.stdout };
  } catch {
    return undefined;
  }
}

/**
 * 操作を 1 つ実行する。
 *
 * **`--raw` / `--json` は付けない。** 付けるとアクション系の出力が空になり、
 * 成功と失敗が区別できなくなる（script-cli-roundtrip 2 節）。
 * 判定は「終了コード」と「`### Error` セクション」の**両方**を見る —
 * 存在しない ref への click は終了コード 0 で `### Error` だけを返す（実測 2026-09-15）。
 */
export async function runAction(ctx: OperationContext, args: string[]): Promise<ActionResult> {
  const full = [`-s=${ctx.session}`, ...args];
  assertAllowedCommand(full);
  const command = redactCommand(args);
  const result = await runCli(ctx.playwright, full, ctx.run);
  const parsed = parseOutput(result.stdout);
  const page = parsePageSection(parsed);
  const meta = { command, exitCode: result.code };

  if (result.timedOut) {
    return {
      ...meta,
      ok: false,
      text: `操作が ${Math.round(ctx.run.timeoutMs / 1000)} 秒で終わりませんでした。ページが応答していない可能性がある。`,
      page,
    };
  }
  const error = errorText(parsed);
  if (error)
    return { ...meta, ok: false, text: error, page };
  if (result.code !== 0)
    return { ...meta, ok: false, text: result.stderr.trim() || `playwright-cli が終了コード ${result.code} を返しました`, page };

  const ran = parsed.sections.find(s => s.name === 'Ran Playwright code');
  const where = page.url ? `現在地: ${page.url}` : '';
  return {
    ...meta,
    ok: true,
    // ページ本文は返さない。「操作は通った、次は observe」だけを伝える。
    text: ['操作は成功した。', where, 'ページの状態は変わった可能性がある。ref を使う前に observe を呼び直すこと。']
      .filter(Boolean).join(' '),
    page,
    ranCode: ran?.body,
  };
}

/** セッションが存在するか。`playwright-cli list --json` の `browsers[].name` を見る。 */
export async function sessionExists(
  playwright: CliLauncher, session: string, run: RunOptions
): Promise<{ exists: boolean; known: string[] }> {
  const result = await runCli(playwright, ['list', '--json'], run);
  let parsed: { browsers?: { name?: string; status?: string }[] };
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    throw new ObserveError(`playwright-cli list の出力を JSON として読めませんでした: ${result.stdout.slice(0, 200)}`);
  }
  const known = (parsed.browsers ?? []).map(b => b.name).filter((n): n is string => !!n);
  return { exists: known.includes(session), known };
}
