export interface ResultEntry {
  index: number;
  prompt: string;
  path: string;
  resolved_path: string;
  success: boolean;
  response: string | null;
  error: string | null;
}

export interface MakeEntryOptions {
  rawPath?: string;
  resolvedPath?: string;
  success: boolean;
  response?: string | null;
  error?: string | null;
  index?: number;
  prompt?: string;
}

/**
 * ResultEntry オブジェクトを生成するファクトリ関数
 */
export function makeEntry(options: MakeEntryOptions): ResultEntry {
  return {
    index: options.index ?? 1,
    prompt: options.prompt ?? '',
    path: options.rawPath ?? '',
    resolved_path: options.resolvedPath ?? '',
    success: options.success,
    response: options.response ?? null,
    error: options.error ?? null,
  };
}

function getHeading(entry: ResultEntry): string {
  if (entry.path) {
    return `${entry.index} · ${entry.path}`;
  }
  return String(entry.index);
}

/**
 * ResultEntry 配列を Markdown 形式にフォーマットする
 */
export function formatMarkdown(entries: ResultEntry[]): string {
  const blocks: string[] = [];
  for (const entry of entries) {
    let body: string;
    if (entry.success) {
      body = entry.response ?? '';
    } else {
      body = `⚠ エラー: ${entry.error ?? '不明なエラー'}`;
    }
    blocks.push(`## ${getHeading(entry)}\n\n${body}\n`);
  }
  return blocks.join('\n');
}

/**
 * ResultEntry 配列を JSON 形式にフォーマットする
 */
export function formatJson(entries: ResultEntry[]): string {
  return JSON.stringify(entries, null, 2);
}

export type OutputFormat = 'markdown' | 'json';

/**
 * CLI オプションと実行結果に応じた最終出力テキストを生成する
 */
export function formatResults(
  entries: ResultEntry[],
  options: {
    format?: OutputFormat;
    parallel?: boolean;
  } = {}
): string {
  const { format, parallel } = options;

  if (format === 'json') {
    return formatJson(entries);
  }

  if (parallel) {
    // --parallel 時のデフォルトは markdown
    return formatMarkdown(entries);
  }

  // 単発実行で format 未指定の場合は応答本文（またはエラー）のみ
  if (!format) {
    if (entries.length === 0) {
      return '';
    }
    const first = entries[0];
    if (first.success) {
      return first.response ?? '';
    }
    return `エラー: ${first.error ?? '不明なエラー'}`;
  }

  return formatMarkdown(entries);
}
