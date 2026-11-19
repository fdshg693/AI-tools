/**
 * ref 集合の保持と照合。
 *
 * **モデルに ref を生成させない**ための層。`pwq` の「ref をモデルに生成させない」と同じ線で、
 * 1 文字違いで別の要素をクリックするのが怖いので、ここは緩めない。
 *
 * ref の抽出は表の列構造ではなく文字列全体からのトークン走査で行う（`pwq/src/ask.ts` と同じ正規表現）。
 * pwq の出力形（ダイジェストの markdown 表 / 閾値以下の素通し YAML）が変わっても壊れないため。
 */

/** ref らしきトークン。`e12` と、遷移で前置きが付いた `f1e12` の両方。 */
const REF_TOKEN = /\b((?:f\d+)?e\d+)\b/g;

export function extractRefs(text: string): string[] {
  return [...new Set(text.match(REF_TOKEN) ?? [])];
}

/** ダイジェストの ref 表（`| ref | role | name |`）の行。名前が無い行もあるので role だけは必ず取る。 */
const REF_ROW = /^\|\s*((?:f\d+)?e\d+)\s*\|([^|]*)\|([^|]*)\|\s*$/;

/**
 * ref → 見出し（`ボタン「カートに追加」` の形）。**操作ログ用**であって、照合には使わない。
 * 表が出ない形式（pwq が素通しした生 YAML 等）では空になるだけで、照合は REF_TOKEN 側が担保する。
 */
export function parseRefLabels(digestText: string): [string, string][] {
  const out: [string, string][] = [];
  for (const line of digestText.split('\n')) {
    const m = line.match(REF_ROW);
    if (!m)
      continue;
    const role = m[2].trim();
    const name = m[3].trim();
    if (role === 'role' || role === '---')
      continue;
    out.push([m[1], name ? `${role}「${name}」` : role]);
  }
  return out;
}

export type RefCheck =
  | { ok: true }
  | { ok: false; reason: string };

/**
 * 直近の観測が返した ref 集合。
 *
 * `stale` は「操作したがまだ observe していない」状態。操作が新しく作った要素の ref は
 * observe するまで存在しない（script-cli-roundtrip 2 節と同じ理由）ので、
 * **操作のたびに立てて、observe のたびに倒す**。
 */
export class RefStore {
  private _refs = new Set<string>();
  private _labels = new Map<string, string>();
  private _stale = true;
  private _observed = false;

  /** observe / find の結果で更新する。ここでしか ref は増えない。 */
  update(digestText: string): number {
    this._refs = new Set(extractRefs(digestText));
    for (const [ref, label] of parseRefLabels(digestText))
      this._labels.set(ref, label);
    this._stale = false;
    this._observed = true;
    return this._refs.size;
  }

  /**
   * ref の見出し（role + name）。操作ログを **pwdo 側で決定論的に組み立てる**ために持つ。
   * 見つからなければ ref そのものを返す。
   */
  label(ref: string): string {
    return this._labels.get(ref) ?? ref;
  }

  /** 操作した。次に ref を使う前に observe が要る。 */
  markStale(): void {
    this._stale = true;
  }

  get size(): number {
    return this._refs.size;
  }

  get stale(): boolean {
    return this._stale;
  }

  has(ref: string): boolean {
    return this._refs.has(ref);
  }

  /**
   * ツール実行の**直前**に呼ぶ。外れたら実行しない。
   * 返す理由文はそのままモデルへ渡るので、次に何をすればよいかまで書く。
   */
  check(ref: string): RefCheck {
    if (!this._observed)
      return { ok: false, reason: 'まだ observe していないので ref が 1 つも無い。先に observe を呼ぶこと。' };
    if (this._stale) {
      return {
        ok: false,
        reason:
          '直前の操作でページが変わったため、手元の ref 表は古い。' +
          '操作が新しく作った要素の ref は observe するまで存在しない。先に observe を呼び直すこと。',
      };
    }
    if (!this._refs.has(ref)) {
      return {
        ok: false,
        reason:
          `ref '${ref}' は直近の observe の結果に無い（現在 ${this._refs.size} 件）。` +
          'ref を自分で組み立てないこと。observe をやり直して、返ってきた表の ref をそのまま使う。' +
          '表が長くて切れているなら find でテキストから絞る。',
      };
    }
    return { ok: true };
  }
}
