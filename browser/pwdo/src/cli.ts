import path from 'node:path';
import process from 'node:process';

import {
  baseDir, ConfigError, loadDotenv, loadModels, missingKeyMessage, readPackageVersion, resolveApiKey, resolveModel,
  type ResolvedModel,
} from './config.js';
import { PwdoError, resolvePlaywrightCli, resolvePwq, type RunOptions } from './passthrough.js';
import { ObserveError, probePageInfo, sessionExists, type OperationContext } from './observe.js';
import { hostOf, isAuthUrl, snapshotHasCredentialField } from './guards.js';
import type { PageInfo } from './parse.js';
import { createTools, DelegationState } from './tools.js';
import { runLoop, type LoopOutcome } from './loop.js';
import { allocateRunDir, finishRecording, startRecording, type Recording, type Recovery } from './script.js';
import { buildReport, EXIT_CODE, renderReport, type ReportInput, type Status } from './report.js';
import { fetchModelPrice, type ModelPrice } from './pricing.js';

/**
 * CLI 骨格。
 *
 * `pwq` と違って**素通しをしない**（自分のコマンドしか受けない）ので、`--pwdo-` 接頭辞は持たない。
 * `-s=` の綴りだけ playwright-cli から借りる。呼び出し側が同じ文字列を使い回せる方が効く。
 *
 * 終了コードは自前で定義する: done=0 / needs-confirmation=10 / blocked=11 /
 * budget-exceeded=12 / failed=1。**done 以外は必ず非ゼロ** —
 * `pwdo ... && next-command` が needs-confirmation で黙って進むのが一番危ない。
 */

const DEFAULTS = {
  maxSteps: 20,
  maxUsd: 0.05,
  timeoutSec: 180,
  stepTimeoutSec: 60,
  /** git ルート（git 管理外なら cwd）からの相対。`--store` の明示値は cwd 基準 */
  store: path.join('.playwright-cli', 'pwdo'),
};

/** 1 回の playwright-cli / pwq 呼び出しの上限。ステップ上限より短くないと意味が無い。 */
const CLI_TIMEOUT_MS = 60_000;

interface Options {
  command?: string;
  session?: string;
  instruction?: string;
  model?: string;
  maxSteps: number;
  maxUsd: number;
  timeoutSec: number;
  stepTimeoutSec: number;
  /** `--allow` の集積。空なら「最初に観測したオリジンと同一」だけが許可される */
  allow: string[];
  json: boolean;
  noScript: boolean;
  /** `--store` の明示値。未指定なら DEFAULTS.store を git ルート基準で使う */
  store?: string;
  verbose: boolean;
  help: boolean;
  aiHelp: boolean;
  version: boolean;
}

function requireValue(arg: string, value?: string): string {
  if (value === undefined || value === '')
    throw new PwdoError(`${arg} には値が必要です（例: ${arg.split('=')[0]}=値）`);
  return value;
}

function requirePositive(arg: string, value?: string): number {
  const n = Number(requireValue(arg, value));
  if (!Number.isFinite(n) || n <= 0)
    throw new PwdoError(`${arg} には正の数を指定してください`);
  return n;
}

export function parseArgs(argv: string[]): Options {
  const options: Options = {
    maxSteps: DEFAULTS.maxSteps,
    maxUsd: DEFAULTS.maxUsd,
    timeoutSec: DEFAULTS.timeoutSec,
    stepTimeoutSec: DEFAULTS.stepTimeoutSec,
    allow: [],
    json: false,
    noScript: false,
    verbose: false,
    help: false,
    aiHelp: false,
    version: false,
    session: process.env.PLAYWRIGHT_CLI_SESSION?.trim() || undefined,
  };

  const positional: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('-')) {
      positional.push(arg);
      continue;
    }
    const eq = arg.indexOf('=');
    const name = eq === -1 ? arg : arg.slice(0, eq);
    const inline = eq === -1 ? undefined : arg.slice(eq + 1);
    const next = () => inline ?? argv[++i];
    switch (name) {
      case '-s': case '--session': options.session = requireValue(arg, next()); break;
      case '--model': options.model = requireValue(arg, next()); break;
      case '--max-steps': options.maxSteps = requirePositive(arg, next()); break;
      case '--max-usd': options.maxUsd = requirePositive(arg, next()); break;
      case '--timeout': options.timeoutSec = requirePositive(arg, next()); break;
      case '--step-timeout': options.stepTimeoutSec = requirePositive(arg, next()); break;
      // 繰り返し指定もカンマ区切りも受ける。既定（オリジン同一）は空配列で表す——
      // 「指定しなければ何でも可」にしない。
      case '--allow':
        options.allow.push(...requireValue(arg, next()).split(',').map(v => v.trim()).filter(Boolean));
        break;
      case '--store': options.store = requireValue(arg, next()); break;
      case '--json': options.json = true; break;
      case '--no-script': options.noScript = true; break;
      case '--verbose': options.verbose = true; break;
      case '--help': case '-h': options.help = true; break;
      case '--ai-help': options.aiHelp = true; break;
      case '--version': case '-v': options.version = true; break;
      default:
        throw new PwdoError(`不明なオプション: ${arg}\n\`pwdo --help\` を見てください。`);
    }
  }

  options.command = positional[0];
  options.instruction = positional.slice(1).join(' ') || undefined;
  return options;
}

function printHelp(): void {
  console.log(`pwdo - ブラウザ操作の一区間を安いAIへ委譲する

使い方:
  pwdo -s=<session> do "<1段落の指示>" [オプション]
  pwdo -s=<session> tools      モデルに見せるツールセットを出す（LLM 不要）
  pwdo models                  モデル一覧と鍵の解決状況（LLM 不要）

セッションは呼び出し側が用意します。pwdo は既存セッションを要求し、
無ければ作らずに failed で落ちます（open / close は一切しません）。

オプション:
  -s=<session>          必須。既存セッション名（既定: PLAYWRIGHT_CLI_SESSION）
  --model=<alias>       使うモデル（\`pwdo models\` で一覧）
  --max-steps=<n>       ツール呼び出しの上限（既定: ${DEFAULTS.maxSteps}）
  --max-usd=<x>         概算コスト上限（既定: ${DEFAULTS.maxUsd}）
  --timeout=<sec>       委譲全体の上限（既定: ${DEFAULTS.timeoutSec}）
  --step-timeout=<sec>  1 ステップの上限（既定: ${DEFAULTS.stepTimeoutSec}）
  --allow=<host>        移動を許す範囲を足す（既定: 現在のオリジンと同一。'*' で全許可）
  --json                返却スキーマを JSON で出す（既定は markdown）
  --no-script           recording-* を張らない
  --store=<dir>         ストアのルート（既定: <git ルート>/${DEFAULTS.store}。相対は cwd 基準）
  --verbose             ステップを stderr へ流す（stdout の契約は変えません）

終了コード: done=0 / needs-confirmation=10 / blocked=11 / budget-exceeded=12 / failed=1

契約の正は tools/browser/pwdo/README.md です。`);
}

function printAiHelp(): void {
  console.log(`pwdo は「ブラウザ操作の一区間」を安いモデルへ渡し、報告だけを返します。

返るのは 3 点だけ: 進んだ状態の生きたセッション / 回収スクリプトのパス / 短い報告。
**snapshot 本文とページ本文は返りません。** 委譲後にページを見るには自分で
\`pwq -s=<session> snapshot\` を撃ってください（\`next\` にも必ず入っています）。

  pwdo -s=shop do "カタログから Wireless Mouse を探してカートに入れる" --json

status で分岐してください:
  done               達成。evidence を読んで、必要なら自分で確かめる
  needs-confirmation 不可逆操作の手前で停止。最後の一手は人間の確認を取って自分で打つ
  blocked            続行不能。reason（login-wall / unsupported-action / …）で分岐
  budget-exceeded    上限に当たった。区間を細かく切って委譲し直すか、自分でやる
  failed             委譲が成立しなかった。error を読む（環境の問題）`);
}

function printModels(): number {
  const env = loadDotenv();
  const config = loadModels();
  console.log(`models: ${config.sourcePath}`);
  console.log(`default: ${config.default}`);
  for (const [alias, spec] of Object.entries(config.models)) {
    const auth = resolveApiKey(spec.provider);
    const key = auth ? 'key ok' : 'key 無し';
    console.log(`- ${alias}${spec.enable ? '' : ' (disabled)'} — ${spec.provider}/${spec.id} [${key}] ${spec.description}`);
  }
  console.log(env.loaded ? `.env: ${env.path}` : `.env: ${env.path}（ファイルがありません）`);
  return 0;
}

function printTools(): number {
  // 実行はしないのでダミーの実行コンテキストでよい。ここは「何が見えているか」を出すだけ。
  const dummy = undefined as unknown as OperationContext;
  const tools = createTools(dummy, new DelegationState());
  for (const [name, definition] of Object.entries(tools))
    console.log(`- ${name}: ${(definition as { description?: string }).description ?? '(説明なし)'}`);
  return 0;
}

/** 委譲が成立しなかったときの出力。report と同じ形で返す（呼び出し側の分岐を 1 本にするため）。 */
function emitFailure(options: Options, model: ResolvedModel | undefined, message: string): number {
  const report = buildReport({
    status: 'failed',
    session: options.session ?? '',
    instruction: options.instruction ?? '',
    modelAlias: model?.alias ?? (options.model ?? ''),
    modelId: model?.spec.id ?? '',
    steps: 0,
    log: [],
    page: {},
    error: message,
    environment: true,
    inputTokens: 0,
    outputTokens: 0,
  });
  console.log(options.json ? JSON.stringify(report, null, 2) : renderReport(report));
  return EXIT_CODE.failed;
}

/**
 * 終了状態の 5 値への畳み込み。README の契約どおりで、ここから増やさない。
 * 記録の停止より **前** に決めるのは、回収スクリプトのヘッダーに status を載せるため。
 */
function decideStatus(outcome: LoopOutcome): Status {
  // 認証壁が最優先。モデルの申告（finish）より先に見る。
  if (outcome.auth)
    return 'blocked';
  if (outcome.finish?.kind === 'done')
    return 'done';
  if (outcome.finish?.kind === 'give_up')
    return 'blocked';
  if (outcome.pending)
    return 'needs-confirmation';
  if (outcome.limit)
    return 'budget-exceeded';
  return 'failed';
}

/**
 * 返却物に載せる最終 URL。**どの終了状態でも落とさない**（Step3 の完了条件）。
 *
 * 1 度も観測せずに終わった走行（最初の observe で落ちた等）では state に URL が無いので、
 * ここで現在地だけを取りに行く。本文は捨てる —— 目的は「呼び出し側がブラウザを見に行かずに済むこと」であって、
 * ページを読むことではない。認証壁で終わった走行では**撃たない**（ホストは AuthWall が持っている）。
 */
async function finalPage(ctx: OperationContext, outcome: LoopOutcome): Promise<PageInfo> {
  if (outcome.auth || outcome.state.page.url)
    return outcome.state.page;
  const probe = await probePageInfo(ctx);
  if (!probe)
    return outcome.state.page;
  // 復帰用の 1 撃がログイン画面に当たることはありうる。そのときはホストだけに落とす
  // （認証境界の観測層と同じ判定を使う。ここだけ緩めない）。
  if (isAuthUrl(probe.page.url) || snapshotHasCredentialField(probe.text))
    return { url: hostOf(probe.page.url) };
  return probe.page;
}

async function runDo(options: Options): Promise<number> {
  if (!options.session)
    return emitFailure(options, undefined, '-s=<session> が指定されていません（PLAYWRIGHT_CLI_SESSION も未設定）。');
  if (!options.instruction)
    return emitFailure(options, undefined, '指示が空です。`pwdo -s=<session> do "<指示>"` の形で渡してください。');

  const env = loadDotenv();
  let model: ResolvedModel;
  try {
    model = resolveModel(loadModels(), options.model);
  } catch (err) {
    if (err instanceof ConfigError)
      return emitFailure(options, undefined, err.message);
    throw err;
  }

  // 鍵が無いのは fatal。ここは pwq と逆で、pwdo は LLM が無ければ 1 ステップも進めない。
  const auth = resolveApiKey(model.spec.provider);
  if (!auth)
    return emitFailure(options, model, missingKeyMessage(model.spec.provider, env));

  const cwd = process.cwd();
  const run: RunOptions = { cwd, timeoutMs: CLI_TIMEOUT_MS };
  const playwright = resolvePlaywrightCli();
  const pwq = resolvePwq();

  const { exists, known } = await sessionExists(playwright, options.session, run);
  if (!exists) {
    return emitFailure(options, model,
      `セッション '${options.session}' がありません（pwdo はセッションを作りません）。` +
      `既存: ${known.length ? known.join(', ') : 'なし'}。呼び出し側で playwright-cli -s=${options.session} open してください。`);
  }

  // 単価は開始前に 1 度だけ。失敗しても委譲は落とさない（コスト上限が効かなくなるだけ）。
  let price: ModelPrice | undefined;
  try {
    price = await fetchModelPrice(model.spec.id, auth.apiKey);
  } catch {
    price = undefined;
  }

  const { createModel } = await import('./provider.js');
  const languageModel = await createModel(model.spec.provider, model.spec.id, auth);
  const ctx: OperationContext = { playwright, pwq, session: options.session, run };

  let recording: Recording | undefined;
  if (!options.noScript) {
    const storeRoot = options.store ? path.resolve(cwd, options.store) : path.join(baseDir(cwd), DEFAULTS.store);
    const { dir, id } = allocateRunDir(storeRoot, options.session);
    recording = await startRecording(playwright, options.session, dir, id, run);
  }

  let outcome: LoopOutcome | undefined;
  let status: Status | undefined;
  let recovery: Recovery | undefined;
  /** runLoop が契約を破って例外で抜けた場合の 1 行。報告は返す（回収も返す）。 */
  let crash: string | undefined;
  try {
    outcome = await runLoop({
      model: languageModel,
      instruction: options.instruction,
      ctx,
      maxSteps: options.maxSteps,
      maxUsd: options.maxUsd,
      totalMs: options.timeoutSec * 1000,
      stepMs: options.stepTimeoutSec * 1000,
      price,
      allow: options.allow,
      verbose: options.verbose,
    });
    status = decideStatus(outcome);
  } catch (err) {
    // runLoop は「どう終わっても LoopOutcome を返す」契約だが、破れた日でも
    // 回収スクリプトと報告は返す。ここで投げ直すと、一番復帰情報が要る場面で何も残らない。
    crash = err instanceof Error ? err.message : String(err);
    status = 'failed';
  } finally {
    // 委譲がどう終わっても（例外で抜けても）記録は止めて回収する。途中までのスクリプトは
    // 「どこまで進んだか」の最も正確な記録で、呼び出し側の復帰材料になる。
    // 張りっぱなしのセッションを返さないためでもある。
    if (recording) {
      recovery = await finishRecording(playwright, recording, {
        session: options.session,
        instruction: options.instruction,
        model: model.alias,
        status: status ?? 'failed',
        steps: outcome?.steps ?? 0,
      }, cwd, run).catch(err => ({ note: `回収に失敗しました: ${err instanceof Error ? err.message : String(err)}` }));
    }
  }

  const done: LoopOutcome = outcome ?? {
    state: new DelegationState(),
    steps: 0,
    inputTokens: 0,
    outputTokens: 0,
  };
  const input: ReportInput = {
    status: status!,
    session: options.session,
    instruction: options.instruction,
    modelAlias: model.alias,
    modelId: model.spec.id,
    steps: done.steps,
    log: done.state.log,
    page: await finalPage(ctx, done),
    summary: done.finish?.summary,
    evidence: done.finish?.evidence,
    pending: done.pending,
    reason: done.finish?.reason,
    auth: done.auth,
    limit: done.limit,
    error: crash ?? done.error,
    lastAction: done.state.lastAction,
    script: recovery?.script,
    scriptNote: recovery?.note,
    budgetNote: done.budgetNote,
    inputTokens: done.inputTokens,
    outputTokens: done.outputTokens,
    usd: done.usd,
  };
  const report = buildReport(input);
  console.log(options.json ? JSON.stringify(report, null, 2) : renderReport(report));
  return EXIT_CODE[status!];
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  // --version は引数検査・設定読み込みより前に返す（tool-conventions の --version 契約）
  if (argv.includes('--version')) {
    console.log(`pwdo ${readPackageVersion()}`);
    return 0;
  }
  const options = parseArgs(argv);
  if (options.version) {
    console.log(`pwdo ${readPackageVersion()}`);
    return 0;
  }
  if (options.aiHelp) {
    printAiHelp();
    return 0;
  }
  if (options.help || !options.command) {
    printHelp();
    return 0;
  }

  switch (options.command) {
    case 'do':
      return runDo(options);
    case 'tools':
      return printTools();
    case 'models':
      return printModels();
    default:
      throw new PwdoError(`不明なコマンド: ${options.command}\n\`pwdo --help\` を見てください。`);
  }
}

main()
  .then(code => { process.exitCode = code; })
  .catch(err => {
    if (err instanceof PwdoError || err instanceof ConfigError || err instanceof ObserveError)
      console.error(err.message);
    else
      console.error(err instanceof Error ? err.stack ?? err.message : String(err));
    process.exitCode = EXIT_CODE.failed;
  });
