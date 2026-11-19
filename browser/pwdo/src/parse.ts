/**
 * playwright-cli / pwq のテキスト出力を分解する。
 *
 * 上流の実装は packages/playwright-core/src/tools/backend/response.ts の parseSections()
 * （`text.split(/^### /m)`）。ここはその読み取り側で、同じ切り方に揃えてある。
 * `pwq/src/parse.ts` の必要部分だけを持ってきたもの（pwdo は snapshot ファイルを自分で読まないので、
 * `snapshotLink` / `inlineSnapshot` は持たない）。
 */

export interface Section {
  name: string;
  body: string;
}

export interface ParsedOutput {
  /** セクション扱いしない前置き行。原文のまま */
  preamble: string;
  sections: Section[];
}

/**
 * open / attach が前置きする「セクションに見えるが本文を持たない行」。
 * 素朴に ^### で割ると幽霊セクションになるので、分割前に剥がす。
 */
const PREAMBLE_LINE = /^### (?:Browser|Session) `[^`]*` (?:opened|created|closed|attached|detached)[^\n]*\n?/;

export function parseOutput(text: string): ParsedOutput {
  let rest = text;
  let preamble = '';
  let m: RegExpMatchArray | null;
  while ((m = rest.match(PREAMBLE_LINE)) && m.index === 0) {
    preamble += m[0];
    rest = rest.slice(m[0].length);
  }

  const sections: Section[] = [];
  for (const chunk of rest.split(/^### /m)) {
    if (!chunk)
      continue;
    const nl = chunk.indexOf('\n');
    if (nl === -1) {
      sections.push({ name: chunk.trim(), body: '' });
      continue;
    }
    sections.push({ name: chunk.slice(0, nl).trim(), body: chunk.slice(nl + 1).replace(/\n+$/, '') });
  }
  return { preamble, sections };
}

export function findSection(parsed: ParsedOutput, name: string): Section | undefined {
  return parsed.sections.find(s => s.name === name);
}

/** 先頭が一致するセクション。pwq は `Snapshot (pwq digest)` のように接尾辞を付ける。 */
export function findSectionStartingWith(parsed: ParsedOutput, prefix: string): Section | undefined {
  return parsed.sections.find(s => s.name === prefix || s.name.startsWith(prefix + ' '));
}

/**
 * `### Error` セクション。
 *
 * **終了コードだけを見てはいけない。** `playwright-cli click e999` は存在しない ref でも
 * 終了コード 0 を返し、`### Error` セクションだけで失敗を伝える（実測 2026-09-15）。
 */
export function errorText(parsed: ParsedOutput): string | undefined {
  const section = parsed.sections.find(s => s.name === 'Error');
  if (!section)
    return undefined;
  return section.body.trim() || 'Error';
}

export interface PageInfo {
  url?: string;
  title?: string;
  console?: string;
}

export function parsePageSection(parsed: ParsedOutput): PageInfo {
  const section = findSection(parsed, 'Page');
  if (!section)
    return {};
  return {
    url: section.body.match(/^- Page URL: (.+)$/m)?.[1],
    title: section.body.match(/^- Page Title: (.+)$/m)?.[1],
    console: section.body.match(/^- Console: (.+)$/m)?.[1],
  };
}

/** ```js … ``` フェンスの中身。最初の 1 つだけ。 */
export function firstFencedBlock(text: string): string | undefined {
  const m = text.match(/```[a-zA-Z]*\n([\s\S]*?)\n?```/);
  return m?.[1];
}
