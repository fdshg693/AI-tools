import path from 'node:path';

/**
 * playwright-cli のテキスト出力を分解する。
 * 上流の実装は packages/playwright-core/src/tools/backend/response.ts の parseSections()
 * （`text.split(/^### /m)`）。ここはその読み取り側で、同じ切り方に揃えてある。
 */

export interface Section {
  name: string;
  body: string;
}

export interface ParsedOutput {
  /** セクション扱いしない前置き行（`### Browser \`x\` opened with pid N.` 等）。原文のまま */
  preamble: string;
  sections: Section[];
}

/**
 * open / attach が前置きする「セクションに見えるが本文を持たない行」。
 * 素朴に ^### で割ると幽霊セクションになるので、分割前に剥がす。
 */
const PREAMBLE_LINE = /^### (?:Browser|Session) `[^`]*` (?:opened|created|closed|attached|detached)[^\n]*\n?/;

const SNAPSHOT_LINK = /\[Snapshot\]\(([^)]+)\)/;

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

export function hasError(parsed: ParsedOutput): boolean {
  return parsed.sections.some(s => s.name === 'Error');
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

/** Snapshot セクションが指すファイルパス。インラインなら undefined。 */
export function snapshotLink(parsed: ParsedOutput, cwd: string): string | undefined {
  const section = findSection(parsed, 'Snapshot');
  if (!section)
    return undefined;
  const link = section.body.match(SNAPSHOT_LINK)?.[1];
  if (!link)
    return undefined;
  return resolveCliPath(link, cwd);
}

/**
 * 出力中のパスは Windows では `\`、`--filename` 指定時は `/` と混在する。両方を解決する。
 */
export function resolveCliPath(link: string, cwd: string): string {
  return path.resolve(cwd, link.replace(/\\/g, '/'));
}

/** インライン snapshot の本体（```yaml フェンスを剥がしたもの）。ファイル参照なら undefined。 */
export function inlineSnapshot(parsed: ParsedOutput): string | undefined {
  const section = findSection(parsed, 'Snapshot');
  if (!section || SNAPSHOT_LINK.test(section.body))
    return undefined;
  return stripFence(section.body);
}

export function stripFence(body: string): string {
  return body.replace(/^```[a-zA-Z]*\n?/, '').replace(/\n?```\s*$/, '');
}
