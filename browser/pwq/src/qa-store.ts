import fs from 'node:fs';
import path from 'node:path';

/**
 * snapshot（アーティファクト）ごとの Q&A 履歴。
 *
 * `index.jsonl` とは別ファイル（`<id>.chat.jsonl`）に置く。index は
 * 「1 アーティファクト 1 行の追記専用」を保ちたいため。
 */

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
  at: string;
  /** assistant のみ。どのモデルが答えたか */
  model?: string;
}

export class ChatLog {
  readonly file: string;

  constructor(storeDir: string, artifactId: string) {
    this.file = path.join(storeDir, `${artifactId}.chat.jsonl`);
  }

  turns(): ChatTurn[] {
    let text: string;
    try {
      text = fs.readFileSync(this.file, 'utf-8');
    } catch {
      return [];
    }
    const out: ChatTurn[] = [];
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim())
        continue;
      try {
        out.push(JSON.parse(line) as ChatTurn);
      } catch {
        // 壊れた行は無視（追記専用なので途中で切れた行が残りうる）
      }
    }
    return out;
  }

  /** 直近 maxPairs 往復だけを返す。履歴が伸びると入力トークンが膨らむため。 */
  recent(maxPairs: number): ChatTurn[] {
    if (maxPairs <= 0)
      return [];
    const all = this.turns();
    return all.slice(Math.max(0, all.length - maxPairs * 2));
  }

  append(...turns: ChatTurn[]): void {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.appendFileSync(this.file, turns.map(t => JSON.stringify(t)).join('\n') + '\n', 'utf-8');
  }

  clear(): void {
    try {
      fs.rmSync(this.file);
    } catch {
      // 無ければ何もしない
    }
  }
}
