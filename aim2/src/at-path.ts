import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { formatInlineBlock, readTextOrError } from './files.js';

export class AtError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AtError';
  }
}

export interface AtRef {
  start: number;
  end: number;
  rawPath: string;
  resolved: string;
}

/**
 * 相対パスは cwd 基準で解決し、~ をホームディレクトリに展開して絶対パスを返す。
 */
export function resolvePath(rawPath: string, cwd: string): string {
  let expanded = rawPath;
  if (expanded === '~') {
    expanded = os.homedir();
  } else if (expanded.startsWith('~/') || expanded.startsWith('~\\')) {
    expanded = path.join(os.homedir(), expanded.slice(2));
  }

  if (path.isAbsolute(expanded)) {
    return path.resolve(expanded);
  }
  return path.resolve(cwd, expanded);
}

/**
 * @path トークンを除いた残り（指示文）を返す。
 */
export function stripAtRefs(text: string, refs: AtRef[]): string {
  let out = text;
  const sorted = [...refs].sort((a, b) => b.start - a.start);
  for (const ref of sorted) {
    out = out.slice(0, ref.start) + out.slice(ref.end);
  }
  return out.trim();
}

/**
 * 各 @path を対応する本文ブロックへ置換する。
 */
export function expandAtRefs(
  text: string,
  replacements: Array<{ ref: AtRef; block: string }>
): string {
  let out = text;
  const sorted = [...replacements].sort((a, b) => b.ref.start - a.ref.start);
  for (const { ref, block } of sorted) {
    out = out.slice(0, ref.start) + block + out.slice(ref.end);
  }
  return out;
}

function isDriveOnly(prefix: string): boolean {
  return prefix.length === 2 && /^[a-zA-Z]:$/.test(prefix);
}

function isDrivePrefix(token: string): boolean {
  if (token.length < 2 || !/^[a-zA-Z]:/.test(token)) {
    return false;
  }
  return token.length === 2 || token[2] === '/' || token[2] === '\\';
}

function skipPrefix(prefix: string): boolean {
  if (prefix === '.' || prefix === '..' || prefix === '~') {
    return true;
  }
  return isDriveOnly(prefix);
}

function isAscii(ch: string): boolean {
  const code = ch.charCodeAt(0);
  return code >= 0 && code <= 127;
}

function isAsciiAlphanumeric(ch: string): boolean {
  const code = ch.charCodeAt(0);
  return (
    (code >= 48 && code <= 57) || // 0-9
    (code >= 65 && code <= 90) || // A-Z
    (code >= 97 && code <= 122) // a-z
  );
}

/**
 * 次文字が ASCII ファイル名の続きなら、そこで切らない。
 * @foo.py を foo ディレクトリへ誤展開しない、かつ
 * @src/foo.pyを要約して は src/foo.py で切れるようにする。
 */
function isValidCut(prefix: string, token: string): boolean {
  if (prefix === token) {
    return true;
  }
  const nxt = token[prefix.length];
  if (nxt === '/' || nxt === '\\') {
    return false;
  }
  // ASCII かつ 英数字または ._+- ならファイル名継続とみなして切らない
  const isContinuation = isAscii(nxt) && (isAsciiAlphanumeric(nxt) || '._+-'.includes(nxt));
  return !isContinuation;
}

function longestExistingPrefix(token: string, cwd: string): string | null {
  let best: string | null = null;
  for (let i = 1; i <= token.length; i++) {
    const prefix = token.slice(0, i);
    if (skipPrefix(prefix)) {
      continue;
    }
    const target = resolvePath(prefix, cwd);
    if (!fs.existsSync(target)) {
      continue;
    }
    if (!isValidCut(prefix, token)) {
      continue;
    }
    best = prefix;
  }
  return best;
}

/**
 * 未クオートでパスと断定できるトークンか（無ければエラーにする対象）。
 */
export function isExplicitPathToken(token: string): boolean {
  if (token.includes('/') || token.includes('\\')) {
    return true;
  }
  if (
    token.startsWith('./') ||
    token.startsWith('.\\') ||
    token.startsWith('../') ||
    token.startsWith('..\\') ||
    token.startsWith('~/') ||
    token.startsWith('~\\')
  ) {
    return true;
  }
  return isDrivePrefix(token);
}

function parseQuoted(text: string, atIndex: number, quoteIndex: number, cwd: string): AtRef {
  const quote = text[quoteIndex];
  let k = quoteIndex + 1;
  while (k < text.length && text[k] !== quote) {
    k++;
  }
  if (k >= text.length) {
    throw new AtError('引用符が閉じられていません');
  }
  const rawPath = text.slice(quoteIndex + 1, k);
  if (!rawPath) {
    throw new AtError('空のパスです');
  }
  const resolved = resolvePath(rawPath, cwd);
  if (!fs.existsSync(resolved)) {
    throw new AtError(`パスが存在しません: ${rawPath}`);
  }
  return {
    start: atIndex,
    end: k + 1,
    rawPath,
    resolved,
  };
}

function parseAt(text: string, atIndex: number, cwd: string): [AtRef | null, number] {
  const j = atIndex + 1;
  if (j >= text.length) {
    return [null, 1];
  }

  if (text[j] === '"' || text[j] === "'") {
    const ref = parseQuoted(text, atIndex, j, cwd);
    return [ref, ref.end - atIndex];
  }

  let k = j;
  while (k < text.length && !/\s/.test(text[k])) {
    k++;
  }
  const token = text.slice(j, k);
  if (!token) {
    return [null, 1];
  }

  const matched = longestExistingPrefix(token, cwd);
  if (matched !== null) {
    return [
      {
        start: atIndex,
        end: j + matched.length,
        rawPath: matched,
        resolved: resolvePath(matched, cwd),
      },
      matched.length + 1,
    ];
  }

  if (isExplicitPathToken(token)) {
    throw new AtError(`パスが存在しません: ${token}`);
  }

  return [null, 1];
}

/**
 * トークン先頭の @path を左から検出する。言及やメールアドレスは残す。
 */
export function findAtRefs(text: string, cwd: string): AtRef[] {
  const refs: AtRef[] = [];
  let i = 0;
  while (i < text.length) {
    if (text[i] === '@' && (i === 0 || /\s/.test(text[i - 1]))) {
      const [ref, consumed] = parseAt(text, i, cwd);
      if (ref !== null) {
        refs.push(ref);
        i = ref.end;
        continue;
      }
      i += consumed;
      continue;
    }
    i++;
  }
  return refs;
}

export interface PromptExpansionResult {
  expanded: string | null;
  error: string | null;
  refs: AtRef[];
}

/**
 * プロンプト内の @path を展開する。
 * 失敗時は { expanded: null, error: '...', refs: [...] } を返す。
 */
export function tryExpandPrompt(
  prompt: string,
  cwd: string,
  fullContentNames?: Set<string> | null
): PromptExpansionResult {
  let refs: AtRef[];
  try {
    refs = findAtRefs(prompt, cwd);
  } catch (err) {
    return {
      expanded: null,
      error: err instanceof Error ? err.message : String(err),
      refs: [],
    };
  }

  const replacements: Array<{ ref: AtRef; block: string }> = [];
  for (const ref of refs) {
    const { content, error } = readTextOrError(ref.resolved, fullContentNames);
    if (content === null) {
      return {
        expanded: null,
        error: error || `パスの読み込みに失敗しました: ${ref.rawPath}`,
        refs,
      };
    }
    replacements.push({
      ref,
      block: formatInlineBlock(ref.rawPath, ref.resolved, content),
    });
  }

  const expanded = replacements.length > 0 ? expandAtRefs(prompt, replacements) : prompt;
  return {
    expanded,
    error: null,
    refs,
  };
}
