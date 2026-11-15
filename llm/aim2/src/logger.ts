import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { PACKAGE_ROOT } from './config.js';

export const DEFAULT_LOG_DIR = path.join(PACKAGE_ROOT, 'logs');
export const UNKNOWN_TRACE_TOOL = 'unknown';

export interface LogRecord {
  timestamp: string;
  model: string;
  provider?: string;
  prompt: string;
  response?: string | null;
  cost: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  generation_id?: string | null;
  user?: string | null;
  session_id?: string | null;
  batch_id?: string | null;
  thread_id?: string | null;
  trace?: Record<string, string | undefined> | null;
}

const SESSION_ID_TIME_WIDTH = 13;
const SESSION_ID_RANDOM_BYTES = 16;
const MAX_EXPLICIT_SESSION_ID_BYTES = 180;
let lastSessionTimestamp = 0;

/**
 * 時刻順に並ぶ、衝突耐性のある会話セッション ID を生成する。
 *
 * 時刻部を固定幅にしているため、同じ形式の ID を辞書順に並べると
 * 概ね生成時刻順になる。時計が後退した場合はプロセス内で単調性を保つ。
 */
export function newSessionId(now = Date.now()): string {
  const timestamp = Math.max(now, lastSessionTimestamp);
  lastSessionTimestamp = timestamp;
  const timePart = String(timestamp).padStart(SESSION_ID_TIME_WIDTH, '0');
  const randomPart = crypto.randomBytes(SESSION_ID_RANDOM_BYTES).toString('hex');
  return `s${timePart}-${randomPart}`;
}

export function isGeneratedSessionId(sessionId: string): boolean {
  return /^s\d{13}-[0-9a-f]{32}$/.test(sessionId);
}

/**
 * セッション ID をファイル名へ安全に変換する。
 *
 * 生成 ID と Windows で安全な明示 ID は可読名を維持し、それ以外は
 * UTF-8 bytes の base64url 表現へ変換する。`~` を安全な名前から
 * 除外することで、可読名とエンコード名の衝突も避ける。
 */
export function encodeSessionIdForFilename(sessionId: string): string {
  const byteLength = Buffer.byteLength(sessionId, 'utf8');
  if (byteLength > MAX_EXPLICIT_SESSION_ID_BYTES) {
    throw new Error(
      `session ID は UTF-8 で ${MAX_EXPLICIT_SESSION_ID_BYTES} bytes 以下で指定してください`
    );
  }

  const windowsReserved = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/i;
  const safe =
    /^[A-Za-z0-9._-]+$/.test(sessionId) &&
    !sessionId.includes('~') &&
    sessionId !== '.' &&
    sessionId !== '..' &&
    !/[. ]$/.test(sessionId) &&
    !windowsReserved.test(sessionId);
  if (safe) {
    return sessionId;
  }

  return `~${Buffer.from(sessionId, 'utf8').toString('base64url')}`;
}

/**
 * OTel 準拠の 128bit trace ID (32 桁 hex 文字列) を生成する
 */
export function newTraceId(): string {
  return crypto.randomBytes(16).toString('hex');
}

/**
 * trace オブジェクトに trace_id が無ければ補正する
 */
export function resolveTrace(
  trace?: Record<string, string | undefined> | null
): Record<string, string | undefined> {
  const resolved = { ...(trace ?? {}) };
  if (!resolved.trace_id) {
    resolved.trace_id = newTraceId();
  }
  return resolved;
}

/**
 * ツール名として安全なファイルシステム用フォルダ名にサニタイズする
 */
export function sanitizeToolName(toolName: string): string {
  const trimmed = toolName.trim();
  if (!trimmed) {
    return UNKNOWN_TRACE_TOOL;
  }
  // パストラバーサル防止: スラッシュ・バックスラッシュ・ドット連続・特殊文字をアンダースコアに置換
  const sanitized = trimmed
    .replace(/[/\\?%*:|"<>]/g, '_')
    .replace(/\.+/g, '_')
    .replace(/^[_\s]+|[_\s]+$/g, '');
  return sanitized || UNKNOWN_TRACE_TOOL;
}

/**
 * ログレコードの書き出し先ファイルパスを取得する
 */
export function getLogPath(record: LogRecord, baseDir = DEFAULT_LOG_DIR): string {
  const toolRaw = record.trace?.tool;
  const tool = toolRaw ? sanitizeToolName(toolRaw) : UNKNOWN_TRACE_TOOL;
  const date = record.timestamp.slice(0, 10);
  if (record.session_id) {
    return path.join(baseDir, tool, date, `${encodeSessionIdForFilename(record.session_id)}.jsonl`);
  }
  // session_id がない旧呼び出しは、既存の日次ログへ追記できるよう維持する。
  return path.join(baseDir, tool, `${date}.jsonl`);
}

/**
 * ログレコードを JSONL 形式でファイルに追記保存する
 */
export function appendLog(record: LogRecord, baseDir = DEFAULT_LOG_DIR): string {
  const logPath = getLogPath(record, baseDir);
  const dir = path.dirname(logPath);
  fs.mkdirSync(dir, { recursive: true });

  const line = JSON.stringify(record) + '\n';
  fs.appendFileSync(logPath, line, 'utf-8');
  return logPath;
}

/**
 * 実行結果からログレコードを組み立てる
 */
export function buildLogRecord(options: {
  model: string;
  provider?: string;
  prompt: string;
  response?: string | null;
  usage?: {
    promptTokens?: number;
    completionTokens?: number;
    totalTokens?: number;
  };
  generationId?: string | null;
  user?: string | null;
  sessionId?: string | null;
  batchId?: string | null;
  threadId?: string | null;
  trace?: Record<string, string | undefined> | null;
  timestamp?: string;
}): LogRecord {
  // ISO8601 文字列（タイムゾーン付き）
  const timestamp = options.timestamp ?? new Date().toISOString();

  return {
    timestamp,
    model: options.model,
    provider: options.provider,
    prompt: options.prompt,
    response: options.response ?? null,
    cost: null, // MVP では単価計算は未実装（Step 5）
    prompt_tokens: options.usage?.promptTokens ?? null,
    completion_tokens: options.usage?.completionTokens ?? null,
    total_tokens: options.usage?.totalTokens ?? null,
    generation_id: options.generationId ?? null,
    user: options.user ?? null,
    session_id: options.sessionId ?? null,
    batch_id: options.batchId ?? null,
    thread_id: options.threadId ?? null,
    trace: options.trace ?? null,
  };
}
