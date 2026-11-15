import fs from 'node:fs';
import path from 'node:path';
import type { ModelMessage } from 'ai';
import { AimError } from './errors.js';
import {
  DEFAULT_LOG_DIR,
  encodeSessionIdForFilename,
  isGeneratedSessionId,
  newSessionId,
} from './logger.js';

export interface ResolvedSessionId {
  sessionId: string;
  generated: boolean;
}

/** @deprecated `session_id` の導入前の API 名。読み取り互換のため残す。 */
export interface ResolvedThreadId {
  threadId: string;
  generated: boolean;
}

export interface ThreadTurn {
  prompt: string;
  response: string;
  timestamp: string;
}

interface ThreadLogCandidate extends ThreadTurn {
  filePath: string;
  lineNumber: number;
  sequence: number;
  traceId: string;
}

export function resolveSessionId(input?: string): ResolvedSessionId {
  if (input === undefined) {
    return {
      sessionId: newSessionId(),
      generated: true,
    };
  }

  const normalized = input.trim();
  if (!normalized) {
    throw new AimError('--session-id は空でない文字列を指定してください', {
      code: 'CONFIG_ERROR',
    });
  }

  if (/[\x00-\x1f\x7f]/.test(normalized)) {
    throw new AimError('--session-id に制御文字は使えません', {
      code: 'CONFIG_ERROR',
    });
  }

  if (Buffer.byteLength(normalized, 'utf8') > 180) {
    throw new AimError('--session-id は UTF-8 で 180 bytes 以下で指定してください', {
      code: 'CONFIG_ERROR',
    });
  }

  return {
    sessionId: normalized,
    generated: false,
  };
}

/** @deprecated `--thread-id` の互換 API。 */
export function resolveThreadId(input?: string): ResolvedThreadId {
  const resolved = resolveSessionId(input);
  return { threadId: resolved.sessionId, generated: resolved.generated };
}

export function buildThreadMessages(history: ThreadTurn[]): ModelMessage[] {
  const messages: ModelMessage[] = [];

  for (const turn of history) {
    messages.push({ role: 'user', content: turn.prompt });
    messages.push({ role: 'assistant', content: turn.response });
  }

  return messages;
}

export function buildPromptInput(
  history: ThreadTurn[],
  prompt: string
): string | Array<ModelMessage> {
  const historyMessages = buildThreadMessages(history);
  if (historyMessages.length === 0) {
    return prompt;
  }

  return [...historyMessages, { role: 'user', content: prompt }];
}

export function loadSessionHistory(sessionId: string, baseDir = DEFAULT_LOG_DIR): ThreadTurn[] {
  if (!fs.existsSync(baseDir)) {
    return [];
  }

  let sequence = 0;
  const matches: ThreadLogCandidate[] = [];
  const sessionFileName = `${encodeSessionIdForFilename(sessionId)}.jsonl`;

  // 新形式は session ID から日付ディレクトリ配下の1ファイルへ短絡する。
  for (const filePath of listSessionFiles(baseDir, sessionFileName, sessionId)) {
    const text = readTextFile(filePath);
    if (text === null) {
      continue;
    }

    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const parsed = parseSessionCandidate(lines[i], sessionId);
      if (parsed === null) {
        continue;
      }

      matches.push({
        ...parsed,
        filePath,
        lineNumber: i + 1,
        sequence: sequence++,
      });
    }
  }

  // 旧形式は移動・書き換えず、thread_id のあるフラット日次ログだけを
  // 互換検索する。旧 session_id は並列バッチ ID なので解釈しない。
  for (const filePath of listLegacyFlatJsonlFiles(baseDir)) {
    const text = readTextFile(filePath);
    if (text === null) {
      continue;
    }

    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const parsed = parseLegacyThreadCandidate(lines[i], sessionId);
      if (parsed === null) {
        continue;
      }

      matches.push({
        ...parsed,
        filePath,
        lineNumber: i + 1,
        sequence: sequence++,
      });
    }
  }

  matches.sort(compareThreadCandidates);

  const seen = new Set<string>();
  return matches
    .filter((candidate) => {
      const key = [
        candidate.timestamp,
        candidate.prompt,
        candidate.response,
        candidate.traceId,
      ].join('\u0000');
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .map(({ prompt, response, timestamp }) => ({
    prompt,
    response,
    timestamp,
    }));
}

/** @deprecated `session_id` の導入前の API 名。 */
export function loadThreadHistory(threadId: string, baseDir = DEFAULT_LOG_DIR): ThreadTurn[] {
  return loadSessionHistory(threadId, baseDir);
}

function listSessionFiles(rootDir: string, fileName: string, sessionId: string): string[] {
  const files: string[] = [];
  const toolDirs = readDirectories(rootDir);
  const preferredDate = generatedSessionDate(sessionId);

  for (const toolDir of toolDirs) {
    const dateDirs = readDirectories(toolDir);
    dateDirs.sort((a, b) => {
      const aDate = path.basename(a);
      const bDate = path.basename(b);
      if (preferredDate && aDate === preferredDate) return -1;
      if (preferredDate && bDate === preferredDate) return 1;
      return aDate.localeCompare(bDate);
    });

    for (const dateDir of dateDirs) {
      const candidate = path.join(dateDir, fileName);
      try {
        if (fs.statSync(candidate).isFile()) {
          files.push(candidate);
        }
      } catch {
        // ファイルが同時に削除された場合は無視する。
      }
    }
  }
  return files;
}

function listLegacyFlatJsonlFiles(rootDir: string): string[] {
  const files: string[] = [];
  for (const toolDir of readDirectories(rootDir)) {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(toolDir, { withFileTypes: true });
    } catch {
      continue;
    }
    entries
      .filter((entry) => entry.isFile() && entry.name.endsWith('.jsonl'))
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((entry) => files.push(path.join(toolDir, entry.name)));
  }
  return files;
}

function readDirectories(dir: string): string[] {
  try {
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((entry) => path.join(dir, entry.name));
  } catch {
    return [];
  }
}

function generatedSessionDate(sessionId: string): string | null {
  if (!isGeneratedSessionId(sessionId)) {
    return null;
  }
  const match = /^s(\d{13})-/.exec(sessionId);
  if (!match) {
    return null;
  }
  return new Date(Number(match[1])).toISOString().slice(0, 10);
}

function readTextFile(filePath: string): string | null {
  try {
    return fs.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}

function parseSessionCandidate(line: string, sessionId: string): ThreadLogCandidate | null {
  const record = parseLogRecord(line);
  if (record === null || record.session_id !== sessionId) {
    return null;
  }
  return toThreadCandidate(record);
}

function parseLegacyThreadCandidate(line: string, threadId: string): ThreadLogCandidate | null {
  const record = parseLogRecord(line);
  if (record === null || record.thread_id !== threadId) {
    return null;
  }
  return toThreadCandidate(record);
}

function parseLogRecord(line: string): Record<string, unknown> | null {
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return null;
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return null;
  }

  return parsed as Record<string, unknown>;
}

function toThreadCandidate(record: Record<string, unknown>): ThreadLogCandidate | null {
  const prompt = typeof record.prompt === 'string' ? record.prompt.trim() : '';
  const response = typeof record.response === 'string' ? record.response.trim() : '';
  const timestamp = typeof record.timestamp === 'string' ? record.timestamp : '';

  if (!prompt || !response || !timestamp) {
    return null;
  }

  const trace = record.trace;
  const traceId =
    trace && typeof trace === 'object' && !Array.isArray(trace) &&
    typeof (trace as Record<string, unknown>).trace_id === 'string'
      ? ((trace as Record<string, unknown>).trace_id as string)
      : '';

  return { prompt, response, timestamp, traceId, filePath: '', lineNumber: 0, sequence: 0 };
}

function compareThreadCandidates(a: ThreadLogCandidate, b: ThreadLogCandidate): number {
  const timestampDiff = a.timestamp.localeCompare(b.timestamp);
  if (timestampDiff !== 0) {
    return timestampDiff;
  }

  const fileDiff = a.filePath.localeCompare(b.filePath);
  if (fileDiff !== 0) {
    return fileDiff;
  }

  const lineDiff = a.lineNumber - b.lineNumber;
  if (lineDiff !== 0) {
    return lineDiff;
  }

  return a.sequence - b.sequence;
}
