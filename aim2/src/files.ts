import fs from 'node:fs';
import path from 'node:path';

export const BINARY_SNIFF_SIZE = 8192;
export const EXCLUDED_DIRECTORY_NAMES = new Set([
  '.git',
  '__pycache__',
  'node_modules',
  '.venv',
  'venv',
]);

/**
 * --full-content-names のカンマ区切りを Set にする。未指定は null。
 */
export function parseFullContentNames(raw?: string | null): Set<string> | null {
  if (raw === undefined || raw === null) {
    return null;
  }
  const set = new Set<string>();
  for (const item of raw.split(',')) {
    const trimmed = item.trim();
    if (trimmed) {
      set.add(trimmed);
    }
  }
  return set;
}

/**
 * 単発経路で @path の位置に埋め込む本文ブロック。
 */
export function formatInlineBlock(
  rawPath: string,
  resolvedPath: string,
  content: string,
  isDir?: boolean
): string {
  let isDirectory = isDir;
  if (isDirectory === undefined) {
    try {
      isDirectory = fs.statSync(resolvedPath).isDirectory();
    } catch {
      isDirectory = false;
    }
  }
  const kind = isDirectory ? 'DIR' : 'FILE';
  return `--- ${kind}: ${rawPath} ---\n${content}`;
}

export interface ReadResult {
  content: string | null;
  error: string | null;
}

/**
 * パスからテキストを読み込む。
 * ファイルの場合は内容またはエラー、ディレクトリの場合はツリーとファイル内容の文字列を返す。
 */
export function readTextOrError(
  targetPath: string,
  fullContentNames?: Set<string> | null
): ReadResult {
  let stat: fs.Stats;
  try {
    stat = fs.statSync(targetPath);
  } catch {
    return { content: null, error: `パスが存在しません: ${targetPath}` };
  }

  if (stat.isDirectory()) {
    try {
      const text = formatDirectoryText(targetPath, fullContentNames);
      return { content: text, error: null };
    } catch (exc) {
      return { content: null, error: `ディレクトリの読み込みに失敗しました: ${exc}` };
    }
  }

  let raw: Buffer;
  try {
    raw = fs.readFileSync(targetPath);
  } catch (exc) {
    return {
      content: null,
      error: `ファイルの読み込みに失敗しました: ${exc instanceof Error ? exc.message : String(exc)}`,
    };
  }

  const sniffLength = Math.min(raw.length, BINARY_SNIFF_SIZE);
  if (raw.subarray(0, sniffLength).includes(0)) {
    return { content: null, error: 'バイナリファイルのため対象外です。' };
  }

  try {
    const decoder = new TextDecoder('utf-8', { fatal: true });
    const decoded = decoder.decode(raw);
    return { content: decoded, error: null };
  } catch {
    return { content: null, error: 'UTF-8としてデコードできませんでした。' };
  }
}

interface DirectoryEntry {
  fullPath: string;
  relativeParts: string[];
  isDirectory: boolean;
}

function collectDirectoryEntries(dirPath: string): {
  entries: DirectoryEntry[];
  files: DirectoryEntry[];
} {
  const entries: DirectoryEntry[] = [];
  const files: DirectoryEntry[] = [];

  function walk(currentDir: string, relativeParts: string[]): void {
    let names: string[];
    try {
      names = fs.readdirSync(currentDir);
    } catch {
      return;
    }

    const dirNames: string[] = [];
    const fileNames: string[] = [];

    for (const name of names) {
      const fullPath = path.join(currentDir, name);
      try {
        const stat = fs.statSync(fullPath);
        if (stat.isDirectory()) {
          if (!EXCLUDED_DIRECTORY_NAMES.has(name)) {
            dirNames.push(name);
          }
        } else {
          fileNames.push(name);
        }
      } catch {
        // アクセス不能なファイル/ディレクトリはスキップ
      }
    }

    dirNames.sort();
    fileNames.sort();

    for (const name of dirNames) {
      const subParts = [...relativeParts, name];
      const entry: DirectoryEntry = {
        fullPath: path.join(currentDir, name),
        relativeParts: subParts,
        isDirectory: true,
      };
      entries.push(entry);
      walk(entry.fullPath, subParts);
    }

    for (const name of fileNames) {
      const subParts = [...relativeParts, name];
      const entry: DirectoryEntry = {
        fullPath: path.join(currentDir, name),
        relativeParts: subParts,
        isDirectory: false,
      };
      entries.push(entry);
      files.push(entry);
    }
  }

  walk(dirPath, []);
  return { entries, files };
}

interface TreeNode {
  name: string;
  isDirectory: boolean;
  childParts: string[];
}

/**
 * ディレクトリのツリー listing と各ファイル内容を 1 つの文字列にする。
 */
export function formatDirectoryText(
  dirPath: string,
  fullContentNames?: Set<string> | null
): string {
  const { entries, files } = collectDirectoryEntries(dirPath);

  const fileContents = new Map<string, string>();
  const fileErrors = new Map<string, string>();
  const fileFiltered = new Set<string>();

  // treeChildren: key は parent relativeParts をスラッシュで join したもの
  const treeChildren = new Map<string, TreeNode[]>();
  treeChildren.set('', []);

  for (const entry of entries) {
    const parentKey = entry.relativeParts.slice(0, -1).join('/');
    const name = entry.relativeParts[entry.relativeParts.length - 1];
    if (!treeChildren.has(parentKey)) {
      treeChildren.set(parentKey, []);
    }
    treeChildren.get(parentKey)!.push({
      name,
      isDirectory: entry.isDirectory,
      childParts: entry.relativeParts,
    });
    if (entry.isDirectory) {
      const selfKey = entry.relativeParts.join('/');
      if (!treeChildren.has(selfKey)) {
        treeChildren.set(selfKey, []);
      }
    }
  }

  for (const file of files) {
    const relKey = file.relativeParts.join('/');
    const fileName = file.relativeParts[file.relativeParts.length - 1];

    if (fullContentNames !== null && fullContentNames !== undefined && !fullContentNames.has(fileName)) {
      fileFiltered.add(relKey);
      continue;
    }

    const result = readTextOrError(file.fullPath);
    if (result.content !== null) {
      fileContents.set(relKey, result.content);
    } else {
      fileErrors.set(relKey, result.error || '読み込めませんでした。');
    }
  }

  function renderTree(parentKey: string, prefix: string): string[] {
    const children = treeChildren.get(parentKey) || [];
    // ディレクトリが先 (isDirectory: true)、ファイルが後 (isDirectory: false)、同種は名前昇順
    const sorted = [...children].sort((a, b) => {
      if (a.isDirectory !== b.isDirectory) {
        return a.isDirectory ? -1 : 1;
      }
      return a.name.localeCompare(b.name);
    });

    const lines: string[] = [];
    for (let index = 0; index < sorted.length; index++) {
      const item = sorted[index];
      const isLast = index === sorted.length - 1;
      const connector = isLast ? '└── ' : '├── ';
      const childKey = item.childParts.join('/');

      let note = '';
      if (!item.isDirectory && fileErrors.has(childKey)) {
        note = ` [読み込みスキップ: ${fileErrors.get(childKey)}]`;
      } else if (!item.isDirectory && fileFiltered.has(childKey)) {
        note = ' [内容省略（対象外ファイル）]';
      }

      lines.push(`${prefix}${connector}${item.name}${note}`);

      if (item.isDirectory) {
        const childPrefix = prefix + (isLast ? '    ' : '│   ');
        lines.push(...renderTree(childKey, childPrefix));
      }
    }
    return lines;
  }

  const sections: string[] = ['ディレクトリツリー:', '.', ...renderTree('', '')];

  // ファイル内容は相対パス昇順でソート
  const sortedFileKeys = Array.from(fileContents.keys()).sort();
  for (const relKey of sortedFileKeys) {
    const content = fileContents.get(relKey)!;
    sections.push(`\n--- FILE: ${relKey} ---`, content);
  }

  return sections.join('\n');
}
