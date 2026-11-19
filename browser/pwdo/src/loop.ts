import {
  ToolLoopAgent,
  isStepCount,
  type LanguageModel,
  type ModelMessage,
  type StopCondition,
  type ToolSet,
} from 'ai';

import { createApproval, createTools, DelegationState, type FinishCall, type PendingApproval } from './tools.js';
import { compressedObserve, SYSTEM } from './prompts/index.js';
import { createUrlPolicy, type AuthWall } from './guards.js';
import { Budget, type Limit } from './budget.js';
import type { ModelPrice } from './pricing.js';
import type { OperationContext } from './observe.js';

/**
 * ループ本体。
 *
 * `ToolLoopAgent` を使う（`generateText` の手書きループは採らない）。pwdo が要る 4 つ
 * ——ステップ上限・コスト上限・履歴圧縮・不可逆操作の停止—— がすべてコンストラクタ引数で揃うため。
 *
 * ここが持つ pwdo 固有の判断は 2 つだけ:
 *  - **履歴圧縮**（`prepareStep`）。外すと入力トークンがステップ数の 2 乗で伸びて、委譲のコスト前提が崩れる
 *  - **終了状態の決定**。README の 5 値へ畳む
 */

export type { Limit };

export interface LoopOptions {
  model: LanguageModel;
  instruction: string;
  ctx: OperationContext;
  maxSteps: number;
  maxUsd: number;
  totalMs: number;
  stepMs: number;
  price?: ModelPrice;
  /** `--allow` の中身。空なら「最初に観測したオリジンと同一」だけが許可される */
  allow: string[];
  /** ステップの進行を stderr へ流す。stdout の契約は変えない */
  verbose: boolean;
}

export interface LoopOutcome {
  finish?: FinishCall;
  pending?: PendingApproval;
  limit?: Limit;
  /** 認証壁に当たって打ち切った。立っていたら他のどの終了状態よりも優先する */
  auth?: AuthWall;
  /** 委譲が成立しなかったときだけ入る */
  error?: string;
  state: DelegationState;
  steps: number;
  inputTokens: number;
  outputTokens: number;
  usd?: number;
  /** 単価が引けずコスト上限が効かなかったときの 1 行。分岐材料ではなく説明 */
  budgetNote?: string;
}

/**
 * 履歴圧縮。
 *
 * 直近 1 回の観測だけ全文（＝ダイジェスト）で残し、それ以前の observe / find の結果を 1 行へ差し替える。
 * 消すのではなく差し替えるのは、「いつ何を見たか」の筋を残すため
 * （`playwright-app` のようにステップごとに初期化すると、カート操作のような履歴依存シナリオが落ちる）。
 *
 * `prepareStep` の戻り値の `messages` は以降のステップの土台として永続するので、圧縮は 1 度効けば残る。
 */
export function compressHistory(messages: ModelMessage[], refCount: number, url?: string): ModelMessage[] {
  const observationParts: { message: number; part: number }[] = [];
  messages.forEach((message, mi) => {
    if (message.role !== 'tool' || !Array.isArray(message.content))
      return;
    message.content.forEach((part, pi) => {
      if (part.type === 'tool-result' && (part.toolName === 'observe' || part.toolName === 'find'))
        observationParts.push({ message: mi, part: pi });
    });
  });
  // 最後の 1 件は触らない。モデルが今まさに ref を選ぶ材料。
  const stale = observationParts.slice(0, -1);
  if (!stale.length)
    return messages;

  const line = compressedObserve(url, refCount);
  return messages.map((message, mi) => {
    const hits = stale.filter(s => s.message === mi);
    if (!hits.length || message.role !== 'tool' || !Array.isArray(message.content))
      return message;
    return {
      ...message,
      content: message.content.map((part, pi) =>
        hits.some(h => h.part === pi) ? { ...part, output: { type: 'text' as const, value: line } } : part
      ),
    } as ModelMessage;
  });
}

function isAbortLike(err: unknown): boolean {
  const name = (err as { name?: string })?.name ?? '';
  const message = err instanceof Error ? err.message : String(err);
  return name === 'AbortError' || name === 'TimeoutError' || /abort|timed? ?out/i.test(message);
}

export async function runLoop(options: LoopOptions): Promise<LoopOutcome> {
  const state = new DelegationState(createUrlPolicy(options.allow));
  const tools = createTools(options.ctx, state);
  const budget = new Budget({
    maxSteps: options.maxSteps,
    maxUsd: options.maxUsd,
    totalMs: options.totalMs,
    stepMs: options.stepMs,
    price: options.price,
  });

  let loggedUpTo = 0;

  /**
   * コスト・時間の上限。ステップ数は SDK の `isStepCount` が見る（同じ判定を 2 度書かない）。
   * 単価が引けなかったときはコスト側だけが判定されない（{@link Budget}）。
   */
  const outOfBudget: StopCondition<ToolSet> = () => {
    const limit = budget.exceeded();
    return limit === 'usd' || limit === 'timeout';
  };

  const snapshot = () => ({
    state,
    steps: budget.steps,
    inputTokens: budget.inputTokens,
    outputTokens: budget.outputTokens,
    usd: budget.usd(),
    budgetNote: budget.note,
  });

  // **エージェントの構築も try の中で行う。** ここで投げると state（ログ・現在地・最後の 1 手）が
  // 呼び出し側へ渡らず、回収スクリプトのパスだけが残った報告になる。runLoop は例外で抜けない ——
  // どう終わっても state を載せた LoopOutcome を返す、が Step3 の契約。
  try {
    const agent = new ToolLoopAgent({
      model: options.model,
      // system prompt は instructions で渡す。messages に role: 'system' を入れると既定で拒否される
      // （prompt injection 対策）。ページ由来テキストを流す pwdo はその既定をそのまま活かす。
      instructions: SYSTEM,
      tools,
      // 毎ステップ必ずツールを呼ばせる。散文で終わられると done / give_up が取れない。
      toolChoice: 'required',
      // 認証壁は AuthWallError の伝播で止まるのが本筋だが、SDK がツールの例外を
      // 結果に畳んでモデルへ返す経路もあるので、停止条件でも塞ぐ（3 層ガードの外側の保険）。
      stopWhen: [isStepCount(options.maxSteps), outOfBudget, () => !!state.authWall],
      toolApproval: createApproval(state),
      prepareStep: ({ messages }) => ({
        messages: compressHistory(messages, state.lastObservedRefCount, state.page.url),
      }),
      onStepEnd: ({ usage }) => {
        budget.recordStep(usage);
        if (!options.verbose)
          return;
        // ログが伸びていないステップ（done / give_up、否認されたツール呼び出し）は
        // 直前の行を再掲しない。再掲すると同じ操作を 2 回したように読める。
        const line = state.log.length > loggedUpTo ? state.log[state.log.length - 1] : '(操作なし)';
        loggedUpTo = state.log.length;
        process.stderr.write(`[pwdo] step ${budget.steps}: ${line}
  `);
      },
    });

    const result = await agent.generate({
      prompt: options.instruction,
      timeout: { totalMs: options.totalMs, stepMs: options.stepMs },
    });

    // done / give_up / confirm_needed は execute を持たないので、呼ばれた時点でループが止まり、
    // 呼び出し内容は最終ステップの staticToolCalls に残る。
    for (const call of result.staticToolCalls) {
      const input = call.input as { summary?: string; evidence?: string; reason?: string; ref?: string };
      if (call.toolName === 'done' || call.toolName === 'give_up') {
        state.finish = {
          kind: call.toolName,
          summary: input.summary ?? '',
          evidence: input.evidence ?? '',
          reason: call.toolName === 'give_up' ? (input.reason as FinishCall['reason']) : undefined,
        };
        break;
      }
      // 停止の 2 本目（モデルの申告）。**ref はここで照合する** —— 外れた ref をそのまま返すと、
      // 呼び出し側が承認後に別の要素を押しかねない。外れたら ref を落として停止だけ残す。
      if (call.toolName === 'confirm_needed') {
        const ref = typeof input.ref === 'string' && state.refs.has(input.ref) ? input.ref : undefined;
        state.pending = {
          tool: 'click',
          ref,
          label: ref ? state.refs.label(ref) : '(モデルの申告。要素は特定できていません)',
          source: 'model',
          reason: input.reason,
        };
        break;
      }
    }
  } catch (err) {
    // 認証壁はここへ AuthWallError として上がってくる。エラーとしては返さない——
    // 「委譲が成立しなかった」のではなく「認証に触れないという契約どおりに止まった」ため。
    if (state.authWall)
      return { ...snapshot(), auth: state.authWall };
    if (!isAbortLike(err))
      return { ...snapshot(), error: err instanceof Error ? err.message : String(err) };
    return { ...snapshot(), limit: budget.classifyAbort() };
  }

  const base = snapshot();
  // 認証壁が最優先。同じステップでモデルが done を呼んでいても、そちらは採らない。
  if (state.authWall)
    return { ...base, auth: state.authWall };
  if (state.finish)
    return { ...base, finish: state.finish };
  // 不可逆操作で止まった。承認の往復は持たないので、ここが委譲の終わり。
  // **上限より先に見る** —— 最後のステップで停止語に当たった走行を budget-exceeded と報告すると、
  // 呼び出し側は「区間を切って再委譲」へ分岐して、同じ一手をもう一度撃たせることになる。
  if (state.pending)
    return { ...base, pending: state.pending };
  const limit = budget.exceeded();
  if (limit)
    return { ...base, limit };
  return {
    ...base,
    error: 'モデルが done も give_up も呼ばずにループを抜けました。区間を細かく切って委譲し直すか、自分で操作してください。',
  };
}
