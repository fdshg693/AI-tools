/**
 * aria snapshot (YAML) から ref 表と見出し構造を決定論的に抽出する。
 *
 * ここでは一切の推測をしない。ref はキャッシュした snapshot に書かれた文字列をそのまま運ぶ。
 * `eNN` が 1 文字でも化けるとクリックが別要素に当たるため、整形・補完・要約は禁止。
 * 抽出できなかった行は「抽出できなかった」として数だけ報告する。
 */

export interface AriaNode {
  /** YAML 上のインデント（スペース数） */
  indent: number;
  role: string;
  name?: string;
  /** `[ref=e12]` の e12。無い要素もある */
  ref?: string;
  /** `[level=2]` 等のフラグ・属性 */
  attrs: Record<string, string | true>;
  /** `- caption [ref=e17]: 注文一覧` の右辺 */
  inline?: string;
  /** 直下の `- /url: ...` */
  url?: string;
  /** 元の行番号（1 始まり） */
  line: number;
}

export interface SnapshotDigest {
  nodes: AriaNode[];
  interactive: AriaNode[];
  outline: OutlineItem[];
  /** 構文にあてはまらず読み飛ばした行数 */
  unparsedLines: number;
}

export interface OutlineItem {
  depth: number;
  text: string;
}

const NODE_RE =
  /^(?<indent>\s*)-\s+(?<role>[A-Za-z][\w-]*)(?:\s+"(?<name>(?:[^"\\]|\\.)*)")?(?<attrs>(?:\s+\[[^\]]*\])*)\s*(?::\s*(?<inline>.*))?$/;

/** クリック・入力の対象になりうるロール */
const INTERACTIVE_ROLES = new Set([
  'button', 'link', 'textbox', 'searchbox', 'checkbox', 'radio', 'combobox',
  'listbox', 'option', 'slider', 'spinbutton', 'switch', 'menuitem',
  'menuitemcheckbox', 'menuitemradio', 'tab', 'treeitem', 'textarea',
]);

/** ページの骨格として見出しに出すロール */
const LANDMARK_ROLES = new Set([
  'banner', 'navigation', 'main', 'complementary', 'contentinfo', 'region',
  'form', 'search', 'article', 'dialog', 'alertdialog', 'table', 'grid',
  'tablist', 'menu', 'menubar', 'tree', 'list', 'figure', 'blockquote',
]);

/** 本文テキストであって要素ではない疑似ロール */
const TEXT_ROLES = new Set(['text']);

export interface ParsedAria {
  nodes: AriaNode[];
  unparsedLines: number;
}

export function parseAriaSnapshot(yaml: string): ParsedAria {
  const nodes: AriaNode[] = [];
  const lines = yaml.split(/\r?\n/);
  let unparsed = 0;
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    if (!raw.trim())
      continue;
    const urlMatch = raw.match(/^\s*-\s+\/url:\s*(.*)$/);
    if (urlMatch) {
      // 直前のノード（link 等）の属性として畳む
      const parent = nodes[nodes.length - 1];
      if (parent)
        parent.url = urlMatch[1].trim();
      continue;
    }
    const m = raw.match(NODE_RE);
    if (!m || !m.groups) {
      unparsed++;
      continue;
    }
    const role = m.groups.role;
    if (TEXT_ROLES.has(role) && m.groups.name === undefined)
      continue;
    const attrs: Record<string, string | true> = {};
    for (const a of (m.groups.attrs || '').matchAll(/\[([^\]=]+)(?:=([^\]]*))?\]/g))
      attrs[a[1].trim()] = a[2] === undefined ? true : a[2].trim();
    const ref = typeof attrs.ref === 'string' ? attrs.ref : undefined;
    nodes.push({
      indent: m.groups.indent.length,
      role,
      name: m.groups.name !== undefined ? unescapeName(m.groups.name) : undefined,
      ref,
      attrs,
      inline: m.groups.inline?.trim() || undefined,
      line: i + 1,
    });
  }
  return { nodes, unparsedLines: unparsed };
}

function unescapeName(name: string): string {
  return name.replace(/\\(.)/g, '$1');
}

export function digestSnapshot(yaml: string): SnapshotDigest {
  const { nodes, unparsedLines } = parseAriaSnapshot(yaml);

  const interactive = nodes.filter(n =>
    n.ref !== undefined &&
    (INTERACTIVE_ROLES.has(n.role) || n.attrs.cursor === 'pointer')
  );

  return { nodes, interactive, outline: buildOutline(nodes), unparsedLines };
}

function buildOutline(nodes: AriaNode[]): OutlineItem[] {
  // 見出し・ランドマークだけを残し、インデントの相対順位で深さを振り直す
  const picked = nodes.filter(n => n.role === 'heading' || LANDMARK_ROLES.has(n.role));
  const stack: number[] = [];
  const out: OutlineItem[] = [];
  for (const n of picked) {
    while (stack.length && stack[stack.length - 1] >= n.indent)
      stack.pop();
    const depth = stack.length;
    stack.push(n.indent);
    out.push({ depth, text: outlineText(n) });
  }
  return out;
}

function outlineText(n: AriaNode): string {
  const label = n.name ?? n.inline;
  if (n.role === 'heading') {
    const level = typeof n.attrs.level === 'string' ? n.attrs.level : '?';
    return `h${level} ${label !== undefined ? JSON.stringify(label) : '(名前なし)'}`;
  }
  const base = label !== undefined ? `${n.role} ${JSON.stringify(label)}` : n.role;
  return n.ref ? `${base} [ref=${n.ref}]` : base;
}
