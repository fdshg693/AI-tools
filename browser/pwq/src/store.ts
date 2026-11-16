import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { baseDir } from './config.js';

/**
 * アーティファクトストア。
 *
 * 置き場は既定で `<git ルート>/.playwright-cli/pwq/<session>/`（git 管理外なら cwd）。
 * `.playwright-cli` はリポジトリ直下の .gitignore で無視する（認証情報を含みうるため）ので、
 * そこに相乗りすることで「うっかりコミット」を構造的に防ぐ。
 * セッション名でディレクトリを分けるのは、複数ブラウザ運用で ref が混線しないようにするため。
 */

export type ArtifactKind = 'snapshot' | 'result';

export interface ArtifactEntry {
  id: string;
  kind: ArtifactKind;
  /** 実体のファイルパス（絶対） */
  file: string;
  /** 実行した playwright-cli のコマンド名 */
  command: string;
  /** 実行した引数（そのまま再現できるように） */
  argv: string[];
  bytes: number;
  lines: number;
  url?: string;
  title?: string;
  createdAt: string;
}

export const DEFAULT_STORE_SUBDIR = path.join('.playwright-cli', 'pwq');

export function resolveSessionName(sessionArg?: string): string {
  return (sessionArg || process.env.PLAYWRIGHT_CLI_SESSION || '').trim() || 'default';
}

/** セッション名はディレクトリ名になるので、パス区切りなどを潰す。 */
function safeSegment(name: string): string {
  return name.replace(/[^\w.@-]+/g, '_');
}

export class Store {
  readonly dir: string;
  readonly session: string;
  private _indexPath: string;

  constructor(cwd: string, session: string, rootOverride?: string) {
    this.session = session;
    const root = rootOverride ? path.resolve(cwd, rootOverride) : path.join(baseDir(cwd), DEFAULT_STORE_SUBDIR);
    this.dir = path.join(root, safeSegment(session));
    this._indexPath = path.join(this.dir, 'index.jsonl');
  }

  ensureDir(): void {
    fs.mkdirSync(this.dir, { recursive: true });
  }

  entries(): ArtifactEntry[] {
    let text: string;
    try {
      text = fs.readFileSync(this._indexPath, 'utf-8');
    } catch {
      return [];
    }
    const out: ArtifactEntry[] = [];
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim())
        continue;
      try {
        out.push(JSON.parse(line) as ArtifactEntry);
      } catch {
        // 壊れた行は無視する（追記専用なので、途中で切れた行が残りうる）
      }
    }
    return out;
  }

  get(id: string): ArtifactEntry | undefined {
    const all = this.entries();
    // 同じ id が複数あることはないが、後勝ちにしておく
    for (let i = all.length - 1; i >= 0; i--) {
      if (all[i].id === id)
        return all[i];
    }
    return undefined;
  }

  latest(kind?: ArtifactKind): ArtifactEntry | undefined {
    const all = this.entries();
    for (let i = all.length - 1; i >= 0; i--) {
      if (!kind || all[i].kind === kind)
        return all[i];
    }
    return undefined;
  }

  /** 次の ID と書き込み先を予約する。まだ index には載せない。 */
  reserve(kind: ArtifactKind, ext: string): { id: string; file: string } {
    this.ensureDir();
    const prefix = kind === 'snapshot' ? 's' : 'r';
    let max = 0;
    for (const e of this.entries()) {
      const n = Number(e.id.slice(1));
      if (e.id.startsWith(prefix) && Number.isInteger(n) && n > max)
        max = n;
    }
    const id = `${prefix}${max + 1}`;
    return { id, file: path.join(this.dir, `${id}${ext}`) };
  }

  record(entry: ArtifactEntry): void {
    this.ensureDir();
    fs.appendFileSync(this._indexPath, JSON.stringify(entry) + '\n', 'utf-8');
  }

  /** 表示用の相対パス。cwd 配下なら相対、そうでなければ絶対のまま。 */
  displayPath(file: string, cwd: string): string {
    const rel = path.relative(cwd, file);
    return rel && !rel.startsWith('..') ? rel.split(path.sep).join('/') : file;
  }
}

export function countLines(text: string): number {
  if (!text)
    return 0;
  return text.split('\n').length - (text.endsWith('\n') ? 1 : 0);
}
