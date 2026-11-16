import { estimateCostUsd, type ModelPrice } from './pricing.js';

/**
 * 予算。**ステップ数 / 概算コスト / 実時間**の 3 上限をここ 1 か所で持つ。
 *
 * loop.ts から分けてあるのは、上限の意味（いつ効くか・効かないときに何が代わりに守るか）が
 * ループの制御フローとは別の契約だから。README の既定値と**この 3 つのフィールドだけ**が
 * 数値の正で、他の場所に上限のコピーを置かない。
 *
 * ## 効く粒度
 *
 * **ステップ境界でしか効かない。** 実行中の 1 回の API 呼び出しを割り込みで止めることはしない
 * （`playwright-app/NEXT.md` の「強制停止は粒度が粗い」と同じ限界を、pwdo も引き受ける）。
 * したがって:
 *
 * - ステップ上限・コスト上限は**上限をまたぐ 1 ステップぶん超過しうる**。概算の上限としてはそれでよい。
 * - `--timeout` は「委譲全体の締め切り」ではなく**ステップ境界での打ち切り**。
 *   1 ステップが長いと、超過を検知するのはそのステップが終わってからになる。
 *
 * ## 単価が引けなかったとき
 *
 * **コスト上限だけを無効化し、委譲は続ける**（ステップ数と時間が代わりに守る）。
 * 単価取得は OpenRouter の Models API への HTTP で、落ちる理由がブラウザ操作と何の関係も無い。
 * ここで委譲全体を失敗させると、呼び出し側は「ネットワークが一瞬詰まった」だけで区間をやり直すことになる。
 * 代わりに {@link Budget.note} を返却物へ 1 行出して、**上限が 1 つ効いていないことを黙らせない**。
 */

/** どの上限に当たったか。返却物の `limit` フィールドにそのまま出る。 */
export type Limit = 'steps' | 'usd' | 'timeout' | 'step-timeout';

export interface BudgetOptions {
  maxSteps: number;
  maxUsd: number;
  /** 委譲全体の上限（ms）。ステップ境界で判定する */
  totalMs: number;
  /** 1 ステップの上限（ms）。AI SDK 側の `timeout.stepMs` と同じ値 */
  stepMs: number;
  /** 引けなかったら undefined。コスト上限だけが無効になる */
  price?: ModelPrice;
}

/** 単価が引けなかったことを呼び出し側へ知らせる 1 行。分岐材料ではなく説明。 */
const NO_PRICE_NOTE =
  '単価を取得できなかったため、コスト上限（--max-usd）は今回の走行では効いていません' +
  '（ステップ数と時間の上限だけが効きました）。';

export class Budget {
  readonly options: BudgetOptions;
  private readonly _startedAt = Date.now();
  private _steps = 0;
  private _inputTokens = 0;
  private _outputTokens = 0;

  constructor(options: BudgetOptions) {
    this.options = options;
  }

  /** ステップが 1 つ終わった。トークンは累計で持つ（1 ステップぶんの usage が渡る）。 */
  recordStep(usage: { inputTokens?: number; outputTokens?: number }): void {
    this._steps += 1;
    this._inputTokens += usage.inputTokens ?? 0;
    this._outputTokens += usage.outputTokens ?? 0;
  }

  get steps(): number {
    return this._steps;
  }

  get inputTokens(): number {
    return this._inputTokens;
  }

  get outputTokens(): number {
    return this._outputTokens;
  }

  get elapsedMs(): number {
    return Date.now() - this._startedAt;
  }

  /** 概算コスト。単価が無ければ `undefined`（`cost.usd: null` として返る）。 */
  usd(): number | undefined {
    if (!this.options.price)
      return undefined;
    return estimateCostUsd(this.options.price, {
      inputTokens: this._inputTokens,
      outputTokens: this._outputTokens,
    });
  }

  /** 単価が引けなかったときだけ 1 行返る。返却物へそのまま出す。 */
  get note(): string | undefined {
    return this.options.price ? undefined : NO_PRICE_NOTE;
  }

  /**
   * 今どれかの上限に当たっているか。**ステップ境界でだけ呼ぶ。**
   * 当たっていても例外にはしない —— 上限超過は異常ではなく**正常な終了状態**
   * （`budget-exceeded`）で、セッションは生きたまま呼び出し側へ返る。
   */
  exceeded(): Limit | undefined {
    if (this._steps >= this.options.maxSteps)
      return 'steps';
    const spent = this.usd();
    if (spent !== undefined && spent >= this.options.maxUsd)
      return 'usd';
    if (this.elapsedMs >= this.options.totalMs)
      return 'timeout';
    return undefined;
  }

  /**
   * AI SDK 側のタイムアウト（`timeout.totalMs` / `timeout.stepMs`）で中断されたとき、
   * **どちらの締め切りだったか**を経過時間から決める。
   *
   * SDK は全体と 1 ステップを同じ `AbortError` で返すので、区別できるのは経過時間しかない。
   * 9 割を境にしているのは、全体の締め切りで落ちたなら経過は必ず `totalMs` の直近になるため。
   */
  classifyAbort(): Limit {
    return this.elapsedMs >= this.options.totalMs * 0.9 ? 'timeout' : 'step-timeout';
  }
}
