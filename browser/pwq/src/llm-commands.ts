import process from 'node:process';

import fs from 'node:fs';

import { ask, isSkipped, DEFAULT_MAX_CHARS, DEFAULT_MAX_HISTORY, prepare, type AskOutput } from './ask.js';
import { loadModels, ConfigError } from './config.js';
import { estimateCostUsd, fetchModelPrice, formatUsd } from './pricing.js';
import { renderAnswer } from './render.js';
import { ChatLog } from './qa-store.js';
import type { ArtifactEntry, Store } from './store.js';

/**
 * LLM を使うサブコマンド（`ask` / `summarize` / `explore` の要約部）と、
 * LLM を使わない一覧系（`history` / `models`）。
 *
 * cli.ts は「どの経路を通すか」だけを持ち、ここは「何を出すか」を持つ。
 */

export interface OwnFlags {
  model?: string;
  step?: string;
  fresh: boolean;
  noRefs: boolean;
  cost: boolean;
  maxChars: number;
  maxHistory: number;
  question?: string;
  /** 位置引数（[0] はサブコマンド名） */
  positionals: string[];
  /** pwq が解釈しなかったフラグ。下流へ渡す経路（explore）でだけ使う */
  rest: string[];
}

/**
 * `pwq` 自身のサブコマンドに限り、素のフラグ（`--model=` 等）を解釈する。
 * 下流の playwright-cli へ渡らない経路なので、`--pwq-` 接頭辞を要求しない。
 * 互換のため `--pwq-` 付きも splitArgs 側で受けている。
 */
export function parseOwnFlags(args: string[], positionalFrom = 1): OwnFlags {
  const flags: OwnFlags = {
    fresh: false, noRefs: false, cost: false,
    maxChars: DEFAULT_MAX_CHARS, maxHistory: DEFAULT_MAX_HISTORY,
    positionals: [], rest: [],
  };
  const positionals: string[] = [];
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (!arg.startsWith('-')) {
      positionals.push(arg);
      continue;
    }
    const eq = arg.indexOf('=');
    const name = eq === -1 ? arg : arg.slice(0, eq);
    const inline = eq === -1 ? undefined : arg.slice(eq + 1);
    const take = () => inline ?? args[++i];
    switch (name) {
      case '--model': case '-m': flags.model = take(); break;
      case '--step': case '--id': flags.step = take(); break;
      case '--fresh': flags.fresh = true; break;
      case '--no-refs': flags.noRefs = true; break;
      case '--cost': flags.cost = true; break;
      case '--max-chars': flags.maxChars = Number(take()); break;
      case '--max-history': flags.maxHistory = Number(take()); break;
      case '-s': case '--session': if (inline === undefined) i++; break;
      default: flags.rest.push(arg); break;  // 解釈しないフラグ。explore だけが下流へ渡す
    }
  }
  flags.positionals = positionals;
  flags.question = positionals.slice(positionalFrom).join(' ').trim() || undefined;
  return flags;
}

/**
 * `--step` の解決。`s1` / `1` / `latest` を受ける。
 * 省略時は最新の snapshot（無ければ最新のアーティファクト）。
 */
export function resolveTarget(store: Store, step?: string): ArtifactEntry | undefined {
  if (!step || step === 'latest')
    return store.latest('snapshot') ?? store.latest();
  const direct = store.get(step);
  if (direct)
    return direct;
  if (/^\d+$/.test(step))
    return store.get(`s${step}`) ?? store.get(`r${step}`);
  return undefined;
}

export function missingTargetMessage(store: Store, step?: string): string {
  return (
    `キャッシュが見つかりません: ${step ?? '(latest)'}\n` +
    `セッション '${store.session}' のストアに何も無いようです。まず \`pwq snapshot\` を実行するか、` +
    '`pwq cache list` で id を確認してください。'
  );
}

export interface AnswerOptions extends OwnFlags {
  cwd: string;
}

/** ask / summarize 共通。返り値は stdout に出す文字列。 */
export async function answerFor(
  store: Store, entry: ArtifactEntry, question: string | undefined, o: AnswerOptions
): Promise<{ text: string; ok: boolean }> {
  let body: string;
  try {
    body = fs.readFileSync(entry.file, 'utf-8');
  } catch {
    return {
      ok: false,
      text: `キャッシュ本体を読めません: ${entry.file}\n（\`pwq cache list\` で確認してください）`,
    };
  }

  const result = await ask({
    entry, body, storeDir: store.dir, question,
    modelAlias: o.model, maxChars: o.maxChars, maxHistory: o.maxHistory,
    fresh: o.fresh, persist: question !== undefined,
  });

  if (isSkipped(result)) {
    return {
      ok: false,
      text:
        `> [pwq] LLM 層はスキップしました。${result.reason}\n` +
        `> 決定論的ダイジェストは \`pwq cache show ${entry.id}\` から自分で読めます。`,
    };
  }

  return {
    ok: true,
    text: renderAnswer({
      heading: question === undefined ? 'Summary' : 'Answer',
      text: result.text,
      modelLabel: `${result.model.alias} / ${result.model.spec.id}`,
      entryId: entry.id,
      displayFile: store.displayPath(entry.file, o.cwd),
      citedRefs: o.noRefs ? [] : result.citedRefs,
      unknownRefs: result.unknownRefs,
      usageLine: await usageLine(result, o.cost),
      truncated: result.truncated,
      historyTurns: result.historyTurns,
      showHistoryHint: question !== undefined,
    }),
  };
}

async function usageLine(result: AskOutput, wantCost: boolean): Promise<string | undefined> {
  if (!result.usage)
    return undefined;
  const parts = [
    `tokens: in ${result.usage.inputTokens ?? '?'} / out ${result.usage.outputTokens ?? '?'}`,
  ];
  if (wantCost) {
    try {
      const price = await fetchModelPrice(result.model.spec.id, process.env.OPENROUTER_API_KEY);
      if (price)
        parts.push(`cost: 約 ${formatUsd(estimateCostUsd(price, result.usage))}`);
      else
        parts.push('cost: 単価不明（Models API に該当 id なし）');
    } catch (err) {
      parts.push(`cost: 取得失敗（${err instanceof Error ? err.message : String(err)}）`);
    }
  }
  return parts.join(' / ');
}

/** ストアの一覧 + 各アーティファクトの Q&A 往復数。LLM は呼ばない。 */
export function runHistory(store: Store, cwd: string): number {
  const entries = store.entries();
  if (!entries.length) {
    console.log(`（ストアは空です: ${store.displayPath(store.dir, cwd)}）`);
    return 0;
  }
  console.log(`session: ${store.session}  dir: ${store.displayPath(store.dir, cwd)}`);
  console.log('| id | kind | bytes | Q&A | command | url | title |');
  console.log('| --- | --- | ---: | ---: | --- | --- | --- |');
  for (const e of entries) {
    const pairs = new ChatLog(store.dir, e.id).turns().length / 2;
    const cell = (v: string) => v.replace(/\|/g, '\|');
    console.log(
      `| ${e.id} | ${e.kind} | ${e.bytes} | ${pairs || ''} | ${e.command} | ` +
      `${cell(e.url ?? '')} | ${cell(e.title ?? '')} |`
    );
  }
  console.log('');
  console.log('質問は `pwq ask "<質問>" [--step <id>]`。履歴を捨てるなら `--fresh`。');
  return 0;
}

/** モデル一覧。設定ファイルの場所と鍵の有無も出す（診断を 1 コマンドで終わらせるため）。 */
export function runModels(): number {
  let config;
  try {
    config = loadModels();
  } catch (err) {
    console.error(err instanceof ConfigError ? err.message : String(err));
    return 1;
  }
  console.log(`models: ${config.sourcePath}`);
  console.log('| alias | provider | id | enable | 既定 | 説明 |');
  console.log('| --- | --- | --- | --- | --- | --- |');
  for (const [alias, spec] of Object.entries(config.models)) {
    console.log(
      `| ${alias} | ${spec.provider} | ${spec.id} | ${spec.enable ? 'yes' : 'no'} | ` +
      `${alias === config.default ? '←' : ''} | ${spec.description.replace(/\|/g, '\|')} |`
    );
  }
  const prep = prepare();
  console.log('');
  console.log(isSkipped(prep) ? `鍵: 未解決 — ${prep.reason}` : '鍵: OK（OPENROUTER_API_KEY を解決済み）');
  return 0;
}
