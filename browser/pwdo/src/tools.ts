import { tool, type ToolApprovalStatus, type TypedToolCall, type ToolSet } from 'ai';
import { z } from 'zod';

import { find, observe, runAction, type ActionResult, type ObserveResult, type OperationContext } from './observe.js';
import { ObserveError } from './observe.js';
import { RefStore } from './refs.js';
import {
  AuthWallError, createUrlPolicy, describePolicy, hostOf, isAllowedUrl, isAuthUrl, isCredentialLabel,
  isIrreversibleLabel, noteOrigin, resolveTarget, snapshotHasCredentialField,
  type AuthWall, type UrlPolicy,
} from './guards.js';
import { wrapSnapshot } from './prompts/index.js';
import type { PageInfo } from './parse.js';

/**
 * モデルに見せるツール層。実行層（observe.ts）を包み、ここで 2 つの防壁を張る。
 *
 *  1. **ref 検証** — モデルが出した ref を直近の observe の集合と照合し、外れたら実行しない
 *  2. **不可逆操作の停止** — 止めるのはツール層であってモデルではない
 *
 * さらに **認証境界**（guards.ts）の 3 層のうち、入力層をここ（`toolApproval`）に、
 * 遷移層・観測層を各ツールの `execute` の中に置く。判定そのものは guards.ts が持ち、
 * ここは「どこで呼ぶか」だけを決める。
 *
 * どちらも AI SDK の `toolApproval`（`approvalFor`）で実装する。`execute` の中で throw するより素直で、
 * 否認理由がそのままモデルの次ステップの材料になる。
 *
 * 操作ログ（返却物の `log[]`）も**ここで決定論的に組み立てる**。モデルに書かせると
 * ページ本文が混ざるため、ツール名・ref の見出し・入力の長さだけから機械的に作る。
 */

/** ログ 1 行に載せる見出しの上限。長い name をそのまま出すと本文の引用に近づく。 */
const LABEL_MAX = 40;

/**
 * ref 失効のエラー。文言は playwright-core の backend/tab.ts
 * （`Ref ${target} not found in the current page snapshot. Try capturing new snapshot.`）に合わせてある。
 * **これだけが自動再試行の対象**で、他の失敗は再試行しない。
 */
const REF_EXPIRED = /Ref\s+\S+\s+not found in the current page snapshot/i;

export type GiveUpReason =
  | 'unsupported-action'
  | 'login-wall'
  | 'element-not-found'
  | 'page-error'
  | 'instruction-unclear';

export interface FinishCall {
  kind: 'done' | 'give_up';
  summary: string;
  evidence: string;
  reason?: GiveUpReason;
}

/**
 * 実行層が最後に撃った 1 手。**モデルの説明とは別に**返却物へ載せる。
 *
 * 失敗理由をモデルの自己申告だけに頼らないための材料で、`summary` / `evidence` と混ぜない
 * （前者は pwdo が持つ事実、後者はモデルの散文）。
 */
export interface LastAction {
  /** playwright-cli のコマンド。`fill` の値は伏せてある（observe.ts の redactCommand） */
  command: string;
  exitCode: number;
  ok: boolean;
  /** `### Error` の 1 行目だけ。ページ由来なので untrusted 扱いで、長さでも切る */
  error?: string;
}

export interface PendingApproval {
  tool: string;
  ref?: string;
  label: string;
  /**
   * どちらの経路で止まったか。**信頼度が違う**ので混ぜない。
   *  - `stop-word` — ツール層が見出しの停止語で止めた（trusted）
   *  - `model` — モデルが `confirm_needed` を呼んだ（untrusted。`reason` はモデルの散文）
   */
  source: 'stop-word' | 'model';
  /** `source: 'model'` のときだけ入る、モデルが書いた停止理由（長さで切ってある） */
  reason?: string;
}

/** 委譲 1 回ぶんの可変状態。ツールもループも report もこれを見る。 */
export class DelegationState {
  /** 許可範囲。既定は「最初に観測したオリジンと同一」（`createUrlPolicy([])`） */
  readonly policy: UrlPolicy;
  readonly refs = new RefStore();
  readonly log: string[] = [];
  page: PageInfo = {};
  finish?: FinishCall;
  pending?: PendingApproval;
  /** 最後の観測の ref 件数（履歴圧縮の 1 行に使う） */
  lastObservedRefCount = 0;
  /**
   * 認証壁に当たった。立った時点で委譲は終わりで、以降どのツールも実行しない。
   * ページ由来の情報はホストしか持たない（guards.ts の AuthWall）。
   */
  authWall?: AuthWall;
  /** 実行層が最後に撃った 1 手。失敗で終わった走行の「最後に何を試したか」になる */
  lastAction?: LastAction;

  constructor(policy: UrlPolicy = createUrlPolicy([])) {
    this.policy = policy;
  }

  /** 観測・操作のたびに呼ぶ。最初の 1 回だけ許可オリジンが確定する（以降は広がらない）。 */
  notePage(page: PageInfo): void {
    noteOrigin(this.policy, page.url);
    this.page = page;
  }

  pushLog(line: string): void {
    this.log.push(line);
  }

  /**
   * 操作 1 回ぶんの機械的な事実を控える。**成功でも控える** ——
   * モデルが done を呼ばずに落ちた走行で「最後に何を試したか」が残るのはここだけ。
   */
  noteAction(result: ActionResult): void {
    this.lastAction = {
      command: result.command,
      exitCode: result.exitCode,
      ok: result.ok,
      // ページ由来のテキストが混じる（Playwright のエラーは call log にページの断片を載せる）。
      // 1 行目だけに切って、返却物側でさらに長さを切る。
      error: result.ok ? undefined : result.text.split('\n')[0],
    };
  }
}

function clampLabel(label: string): string {
  return label.length > LABEL_MAX ? label.slice(0, LABEL_MAX) + '…' : label;
}

/**
 * ログに載せる遷移先。**認証ドメインならホストだけに落とす。**
 * 認証壁で終わる走行でも `navigate:` の行は残るので、ここを素通しにすると
 * ログイン URL のパス（テナント名・アカウント識別子が入りうる）が返却物へ出る。
 */
function logTarget(to: string): string {
  if (to === 'back' || to === 'reload')
    return to;
  return isAuthUrl(to) ? (hostOf(to) ?? '(認証ドメイン)') : clampLabel(to);
}

/**
 * 遷移層。操作・観測の結果を**モデルへ返す前に**現在地だけ見る。
 * 認証ドメイン／ログインパスに移っていたら、そこで委譲を終える。
 */
function guardUrl(state: DelegationState, page: PageInfo): void {
  if (state.authWall || !isAuthUrl(page.url))
    return;
  state.authWall = { layer: 'navigation', host: hostOf(page.url) };
  throw new AuthWallError(state.authWall);
}

/**
 * 観測層。観測結果に資格情報の入力欄が含まれていたら、**その内容を履歴にも返却物にも載せずに**終える。
 * ref ストアも更新しない（更新すると次のステップで認証画面の要素を押せてしまう）。
 */
function guardObservation(state: DelegationState, text: string, page: PageInfo): void {
  guardUrl(state, page);
  if (!snapshotHasCredentialField(text))
    return;
  state.authWall = { layer: 'observation', host: hostOf(page.url) };
  throw new AuthWallError(state.authWall);
}

/**
 * 不可逆操作の判定は guards.ts が持つ（日本語・英語の停止語）。ここは呼ぶだけ。
 * **停止語だけでは必ず漏れる**ので、モデル側の申告（`confirm_needed`）と二重にしてある。
 */
export { isIrreversibleLabel as isIrreversible };

export function createTools(ctx: OperationContext, state: DelegationState) {
  const applyObservation = (result: ObserveResult, kind: 'observe' | 'find', note: string): string => {
    guardObservation(state, result.text, result.page);
    const count = state.refs.update(result.text);
    state.lastObservedRefCount = count;
    state.notePage(result.page);
    state.pushLog(kind === 'observe' ? `observe: ${count} refs` : `find: ${note} → ${count} refs`);
    return wrapSnapshot(result.text);
  };

  /**
   * 操作 1 回。ログ・ref の失効印・認証の遷移層・最後の 1 手の記録をここに集約する。
   *
   * **自動リトライはしない。ただし ref 失効だけは例外。**
   * `Ref <r> not found in the current page snapshot` は「操作が失敗した」のではなく
   * 「観測が古かった」だけで、**副作用は何も起きていない**（playwright-cli は要素を解決できずに
   * 止まっている）。同じ意図の操作をもう一度打っても二重実行にならないので、
   * observe をやり直して 1 回だけ試す。それ以外の失敗——タイムアウト・クリックは通ったが
   * 遷移しない・サーバーエラー——は打ち直すと副作用が二重になりうるので、
   * モデルにも pwdo にも再試行させず、そのままモデルへ返す
   * （`playwright-app/NEXT.md`「リトライはブラウザ状態をロールバックしない」）。
   */
  const act = async (args: string[], line: string, ref?: string): Promise<string> => {
    let result = await runAction(ctx, args);
    state.refs.markStale();
    state.pushLog(line);
    state.noteAction(result);

    if (ref && !result.ok && REF_EXPIRED.test(result.text)) {
      // 観測のやり直し。認証層（guardObservation）もここを通る——復帰のための observe が
      // 認証画面を撮ってしまう経路を開けない。
      applyObservation(await observe(ctx), 'observe', '');
      if (state.refs.has(ref)) {
        state.pushLog('retry: ref 失効のため observe し直して同じ操作を 1 回だけ再実行');
        result = await runAction(ctx, args);
        state.refs.markStale();
        state.noteAction(result);
      } else {
        // 同じ ref がもう無いなら「観測が古かっただけ」ではない。ここで打ち切ってモデルへ返す。
        state.pushLog('retry: 中止（observe し直しても同じ ref が無い）');
      }
    }

    guardUrl(state, result.page);
    state.notePage(result.page);
    return result.text;
  };

  return {
    observe: tool({
      description:
        '今のページを見る。構造の要約と、操作できる要素の ref 表が返る。' +
        '操作したあとは必ずこれを呼び直すこと（新しく現れた要素の ref は observe するまで存在しない）。',
      inputSchema: z.object({}),
      execute: async () => applyObservation(await observe(ctx), 'observe', ''),
    }),

    find: tool({
      description:
        'ページ内をテキストで検索し、一致した箇所の周辺だけを返す。' +
        'observe の ref 表が長すぎて切れているときに使う。ページ全文を読む手段はこれ以外に無い。',
      inputSchema: z.object({
        text: z.string().describe('探す文字列。ボタン名やリンク名の一部'),
      }),
      execute: async ({ text }) => applyObservation(await find(ctx, text), 'find', JSON.stringify(text)),
    }),

    navigate: tool({
      description: 'ページを移動する。url を渡すとそこへ、back で 1 つ戻る、reload で読み直す。',
      inputSchema: z.object({
        to: z.string().describe("移動先の URL、または 'back' / 'reload'"),
      }),
      execute: async ({ to }) => {
        const args = to === 'back' ? ['go-back'] : to === 'reload' ? ['reload'] : ['goto', to];
        return act(args, `navigate: ${logTarget(to)}`);
      },
    }),

    click: tool({
      description: '要素をクリックする。ref は直近の observe が返したものだけ。',
      inputSchema: z.object({ ref: z.string() }),
      execute: async ({ ref }) => act(['click', ref], `click: ${clampLabel(state.refs.label(ref))}`, ref),
    }),

    fill: tool({
      description: '入力欄に値を入れる。submit を true にすると入力後に Enter を押す。',
      inputSchema: z.object({
        ref: z.string(),
        value: z.string(),
        submit: z.boolean().optional(),
      }),
      execute: async ({ ref, value, submit }) => {
        const label = state.refs.label(ref);
        // 入力した実データは出さない。長さだけ（検索語・住所・メールが会話に残るのを防ぐ）。
        const line = `fill: ${clampLabel(label)} ← ${[...value].length} 文字${submit ? ' + Enter' : ''}`;
        return act(submit ? ['fill', ref, value, '--submit'] : ['fill', ref, value], line, ref);
      },
    }),

    press: tool({
      description: "キーを 1 つ押す（'Enter' / 'Escape' / 'ArrowDown' など）。",
      inputSchema: z.object({ key: z.string() }),
      execute: async ({ key }) => act(['press', key], `press: ${clampLabel(key)}`),
    }),

    select: tool({
      description: 'ドロップダウンの選択肢を選ぶ。value は observe が示した選択肢の文字列。',
      inputSchema: z.object({ ref: z.string(), value: z.string() }),
      execute: async ({ ref, value }) => {
        const line = `select: ${clampLabel(state.refs.label(ref))} ← ${clampLabel(value)}`;
        return act(['select', ref, value], line, ref);
      },
    }),

    check: tool({
      description: 'チェックボックス / ラジオの状態を変える。checked: false で外す。',
      inputSchema: z.object({ ref: z.string(), checked: z.boolean() }),
      execute: async ({ ref, checked }) => {
        const line = `check: ${clampLabel(state.refs.label(ref))} → ${checked ? 'on' : 'off'}`;
        return act([checked ? 'check' : 'uncheck', ref], line, ref);
      },
    }),

    hover: tool({
      description: '要素にマウスを乗せる。ホバーで開くメニューを出すときに使う。',
      inputSchema: z.object({ ref: z.string() }),
      execute: async ({ ref }) => act(['hover', ref], `hover: ${clampLabel(state.refs.label(ref))}`, ref),
    }),

    // done / give_up は execute を持たない。呼ばれた時点でループが止まる（AI SDK の Forced Tool Calling）。
    done: tool({
      description: '指示を達成したときに呼ぶ。根拠が挙げられないなら done ではない。',
      inputSchema: z.object({
        summary: z.string().describe('何をしたか。日本語 1〜2 文。ページ本文は引用しない'),
        evidence: z.string().describe('達成できたと判断した画面上の根拠。どの要素がどう変わったか'),
      }),
    }),

    give_up: tool({
      description: '続行できないときに呼ぶ。黙って別の手段を試すのではなく、これで呼び出し元へ返す。',
      inputSchema: z.object({
        reason: z.enum([
          'unsupported-action',
          'login-wall',
          'element-not-found',
          'page-error',
          'instruction-unclear',
        ]),
        summary: z.string().describe('どこまで進んで、なぜ続けられないか。日本語 1〜2 文'),
        evidence: z.string().describe('そう判断した画面上の根拠'),
      }),
    }),

    /**
     * 不可逆操作の停止の **2 本目**。停止語（ツール層）は必ず取りこぼすので、
     * モデル自身が「この一手は取り返しがつかない」と判断したら自発的に呼ぶ経路を用意する。
     * `done` / `give_up` と同じく `execute` を持たない（呼ばれた時点でループが止まる）。
     */
    confirm_needed: tool({
      description:
        '次に押そうとしている要素が取り返しのつかない操作（購入・注文の確定・送信・削除・送金など）だと' +
        '判断したら、押さずにこれを呼ぶ。呼び出し元の人間が確認して自分で押す。' +
        '押してから報告するのではなく、**押す前に**呼ぶこと。',
      inputSchema: z.object({
        ref: z.string().describe('押そうとしていた要素の ref（直近の observe の表にあるもの）'),
        reason: z.string().describe('なぜ取り返しがつかないと判断したか。日本語 1 文。ページ本文は引用しない'),
      }),
    }),
  };
}

export type PwdoTools = ReturnType<typeof createTools>;

/**
 * 入力層の否認理由。**そのままモデルへ渡る**ので、代わりに何をすべきかまで書く。
 * ここでページ由来の語（欄の名前）を引かないこと——否認理由はモデルの次の発話に引用されうる。
 */
const AUTH_DENIED =
  '資格情報の入力は実行できません。認証は呼び出し元の人間が行う決まりです。' +
  '別の欄や別の言い方で試さず、give_up（reason: login-wall）で呼び出し元へ返してください。';

/** 認証壁に当たったあとの否認理由。入力層の否認とは別文にする（何が起きたかが違う）。 */
const AUTH_STOPPED =
  '認証が必要な画面に到達したため、この委譲は終了しました。これ以上の操作は実行されません。';

/** ref を引数に取るツール。ここに載っているものだけが ref 照合の対象。 */
const REF_TOOLS = new Set(['click', 'fill', 'select', 'check', 'hover']);

/**
 * 範囲外への遷移の否認理由。**そのままモデルへ渡る**ので、次に何をすべきかまで書く。
 * 許可範囲はホストまでしか載せない（パスを載せると否認理由経由でページ由来情報が漏れる）。
 */
function outOfScopeReason(policy: UrlPolicy, host: string): string {
  return (
    `'${host}' は今回の委譲の許可範囲の外なので移動しません（許可: ${describePolicy(policy)}）。` +
    '別の URL で回り込まず、この区間で必要なら give_up（reason: unsupported-action）で呼び出し元へ返してください。'
  );
}

/**
 * 実行前の関門。`ToolLoopAgent` の `toolApproval` にそのまま渡す。
 *
 * - ref が直近の observe に無い / 観測が古い → `denied`（**実行されない**。理由はモデルへ返る）
 * - 不可逆操作 → `user-approval`（ループが止まり、pwdo は needs-confirmation で終了する）
 * - それ以外 → `undefined`（そのまま実行）
 */
export function createApproval(state: DelegationState) {
  return ({ toolCall }: { toolCall: TypedToolCall<ToolSet> }): ToolApprovalStatus => {
    // 認証壁に当たったあとは何も実行しない。停止条件（loop.ts）と二重にしてある——
    // ステップ内に並んだ呼び出しは停止条件より先に走るため、ここでも塞ぐ。
    if (state.authWall)
      return { type: 'denied', reason: AUTH_STOPPED };

    // 範囲。**`navigate` は実行させずに否認する**（外向きの遷移をモデルの自制に任せない）。
    // 否認であって終了ではない —— 範囲外に用があると分かれば、モデルは give_up で呼び出し元へ返せる。
    if (toolCall.toolName === 'navigate') {
      const to = (toolCall.input as { to?: string } | undefined)?.to;
      if (typeof to !== 'string' || !to)
        return { type: 'denied', reason: "移動先が指定されていません（URL か 'back' / 'reload'）。" };
      if (to === 'back' || to === 'reload')
        return undefined;
      const target = resolveTarget(to, state.page.url);
      if (!target)
        return { type: 'denied', reason: 'URL として読めません。observe が示したリンクから移動してください。' };
      if (!state.policy.origins.size && !state.policy.any && !state.policy.hosts.length) {
        return {
          type: 'denied',
          reason: '先に observe を呼んでください（現在地が分からないと移動先の許可範囲を判定できません）。',
        };
      }
      if (!isAllowedUrl(target, state.policy)) {
        state.pushLog(`navigate: 拒否（範囲外 ${hostOf(target) ?? '?'}）`);
        return { type: 'denied', reason: outOfScopeReason(state.policy, hostOf(target) ?? '(不明)') };
      }
      return undefined;
    }

    if (!REF_TOOLS.has(toolCall.toolName))
      return undefined;
    const input = toolCall.input as { ref?: string } | undefined;
    const ref = input?.ref;
    if (typeof ref !== 'string' || !ref)
      return { type: 'denied', reason: 'ref が指定されていません。observe の表から選んでください。' };

    const check = state.refs.check(ref);
    if (!check.ok)
      return { type: 'denied', reason: check.reason };

    const label = state.refs.label(ref);
    // 入力層。資格情報らしき欄への入力は **実行前に** 弾く。終了はさせない——
    // モデルが自分で give_up(login-wall) を選べば、どこまで進んだかが報告に残る。
    if (toolCall.toolName === 'fill' && isCredentialLabel(label)) {
      state.pushLog('fill: 拒否（認証欄）');
      return { type: 'denied', reason: AUTH_DENIED };
    }
    // 停止（1 本目）。停止語に当たったクリックは実行せず、ここで委譲を終える。
    // 2 本目はモデル側の `confirm_needed`（loop.ts で拾う）。**片方だけにしない。**
    if (toolCall.toolName === 'click' && isIrreversibleLabel(label)) {
      state.pending = { tool: toolCall.toolName, ref, label: clampLabel(label), source: 'stop-word' };
      return { type: 'user-approval', reason: `不可逆の可能性がある操作です: ${clampLabel(label)}` };
    }
    return undefined;
  };
}

export { ObserveError };
