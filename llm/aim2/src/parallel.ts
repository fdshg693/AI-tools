import crypto from 'node:crypto';
import type { ModelMessage } from 'ai';
import { runPrompt, type RunResult } from './runner.js';
import { normalizeError, AimError } from './errors.js';
import {
  appendLog,
  buildLogRecord,
  newSessionId,
  resolveTrace,
  DEFAULT_LOG_DIR,
} from './logger.js';
import { buildPromptInput, type ThreadTurn } from './thread.js';
import type { ResultEntry } from './formatter.js';

export const JOBS_MIN = 1;
export const JOBS_MAX = 10;
export const JOBS_DEFAULT = 4;

export interface ParallelTarget {
  index: number;
  expandedPrompt: string;
  sessionId?: string;
  /** @deprecated `sessionId` を使用する。 */
  threadId?: string;
}

export interface RunParallelOptions {
  provider: string;
  modelId: string;
  modelAlias: string;
  jobs?: number;
  entries: ResultEntry[];
  targets: ParallelTarget[];
  traceTool?: string;
  batchId?: string;
  /** @deprecated 旧 API では並列共有 ID を sessionId と呼んでいた。 */
  sessionId?: string;
  logBaseDir?: string;
  runPromptFn?: (
    provider: string,
    modelId: string,
    prompt: string | Array<ModelMessage>,
    options?: { stream?: boolean }
  ) => Promise<RunResult>;
}

/**
 * 軽量 Promise 並行制御プール（同時実行数を最大 concurrency に制限）
 */
export async function pMap<T, R>(
  items: T[],
  mapper: (item: T, index: number) => Promise<R>,
  concurrency: number
): Promise<R[]> {
  if (items.length === 0) {
    return [];
  }
  const effectiveConcurrency = Math.max(1, Math.min(concurrency, items.length));
  const results: R[] = new Array(items.length);
  let currentIndex = 0;

  const workers = Array.from({ length: effectiveConcurrency }, async () => {
    while (currentIndex < items.length) {
      const index = currentIndex++;
      results[index] = await mapper(items[index], index);
    }
  });

  await Promise.all(workers);
  return results;
}

/**
 * 1 回のプロンプト実行を試みる（最大 1 回リトライ、計 2 回試行）
 */
export async function askOnce(options: {
  provider: string;
  modelId: string;
  modelAlias: string;
  prompt: string;
  entry: ResultEntry;
  traceTool?: string;
  sessionId?: string;
  batchId?: string;
  /** @deprecated `sessionId` を使用する。 */
  threadId?: string;
  history?: ThreadTurn[];
  logBaseDir?: string;
  runPromptFn?: (
    provider: string,
    modelId: string,
    prompt: string | Array<ModelMessage>,
    options?: { stream?: boolean }
  ) => Promise<RunResult>;
}): Promise<{ success: boolean; response?: string; error?: string }> {
  let lastError = '';
  const runner = options.runPromptFn ?? runPrompt;
  const traceTool = options.traceTool || 'aim2-cli';
  const promptInput = buildPromptInput(options.history ?? [], options.prompt);

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const trace = resolveTrace({
        tool: traceTool,
        prompt_index: String(options.entry.index),
        ...(options.entry.path ? { file_path: options.entry.path } : {}),
      });

      const result = await runner(options.provider, options.modelId, promptInput, {
        stream: false,
      });

      const trimmed = result.text.trim();
      if (!trimmed) {
        throw new AimError('モデルからの応答が空でした。', {
          code: 'EMPTY_RESPONSE',
          provider: options.provider,
        });
      }

      // トレースログを記録
      try {
        appendLog(
          buildLogRecord({
            model: options.modelAlias,
            provider: options.provider,
            prompt: options.prompt,
            response: trimmed,
            usage: result.usage,
            trace,
            sessionId: options.sessionId,
            batchId: options.batchId,
            threadId: options.threadId,
          }),
          options.logBaseDir ?? DEFAULT_LOG_DIR
        );
      } catch (logErr) {
        // ログ書き込みエラーがあっても推論結果は失敗させない
        console.error(`警告: ログの追記に失敗しました: ${logErr}`);
      }

      return { success: true, response: trimmed };
    } catch (err) {
      const normalized = normalizeError(err, options.provider);
      lastError = normalized.formatUserMessage();
    }
  }

  return { success: false, error: lastError };
}

/**
 * targets で指定された各プロンプトを並行実行し、entries を更新して返す
 */
export async function runParallel(options: RunParallelOptions): Promise<ResultEntry[]> {
  const {
    provider,
    modelId,
    modelAlias,
    jobs = JOBS_DEFAULT,
    entries,
    targets,
    traceTool,
    batchId = options.batchId ?? options.sessionId ?? crypto.randomUUID(),
    logBaseDir,
    runPromptFn,
  } = options;

  if (targets.length === 0) {
    return entries;
  }

  const concurrency = Math.max(JOBS_MIN, Math.min(JOBS_MAX, jobs));

  await pMap(
    targets,
    async (target) => {
      const entry = entries[target.index];
      const res = await askOnce({
        provider,
        modelId,
        modelAlias,
        prompt: target.expandedPrompt,
        entry,
        traceTool,
        sessionId: target.sessionId ?? target.threadId ?? newSessionId(),
        batchId,
        history: [],
        logBaseDir,
        runPromptFn,
      });

      entry.success = res.success;
      if (res.success) {
        entry.response = res.response ?? '';
        entry.error = null;
      } else {
        entry.response = null;
        entry.error = res.error ?? '不明なエラー';
      }
    },
    concurrency
  );

  return entries;
}
