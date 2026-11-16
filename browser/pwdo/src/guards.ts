/**
 * 認証境界。**委譲先を認証に触れさせない**ための判定だけを置く。
 *
 * 前提はスキル sharing-browser-with-user（プラグイン browser）の
 * 「絶対に守ること」1〜2 —— 「**読まない**ではなく**打たない**」（実行した時点で出力が会話に入る）と
 * 「資格情報を受け取らない」。委譲先はユーザーと会話を持たないが、**返却物が呼び出し側の会話に入る**ので、
 * 同じ理屈が 1 段階ずれてそのまま適用される。`pwq` の「ラッパー経由でも認証の契約は緩まない」と同じ立場。
 *
 * **検知語の網羅は目指さない。** サイトごとに表現が違うので必ず取りこぼす。
 * 取りこぼす前提で 3 層に分け、どれか 1 層で止まればよい設計にしてある:
 *
 *  1. **入力層** — 資格情報らしき欄への `fill` を**実行前に**拒否する（{@link isCredentialLabel}）
 *  2. **遷移層** — 認証ドメイン / ログインパスへ移ったら、observe を撃つ前に終了する（{@link isAuthUrl}）
 *  3. **観測層** — 観測結果にパスワード欄が含まれていたら、**その内容を履歴にも返却物にも載せずに**終了する
 *     （{@link snapshotHasCredentialField}）
 *
 * 1 層でも外さないこと。取りこぼしても**パスワード欄への入力そのものは入力層で止まる**、
 * という二段構えが崩れる。
 */

/**
 * 資格情報・ワンタイムコードを示す語。**入力層と観測層で共用する。**
 *
 * 「ログイン」「サインイン」は入れない —— ログイン**ボタン**やリンクの名前に頻出し、
 * 入力層（`fill` の拒否）で誤爆すると普通のフォームが押せなくなる。認証画面そのものの検知は
 * 遷移層（URL）と観測層（入力欄の存在）が担う。
 */
const CREDENTIAL_WORD =
  /(パスワード|暗証|認証コード|確認コード|ワンタイム|合言葉|password|passwd|passphrase|\bpwd\b|passcode|credential|\botp\b|\bmfa\b|\b2fa\b|one[-\s]?time|verification code|security code|authenticator)/i;

/** 認証を担う既知のホスト。ドメインごと認証専用なので、パスを見ずに止める。 */
const AUTH_HOST =
  /(^|\.)(accounts\.google\.com|login\.microsoftonline\.com|login\.live\.com|appleid\.apple\.com|signin\.aws\.amazon\.com|auth0\.com|okta\.com|oktapreview\.com|onelogin\.com|duosecurity\.com|id\.atlassian\.com)$/i;

/**
 * ログイン画面によくあるパス。**前後をスラッシュで区切る**のが肝で、
 * `/authentic-bags` のような無関係なパスを拾わない。
 */
const AUTH_PATH =
  /(^|\/)(login|log-in|signin|sign-in|signon|sso|oauth2?|auth|authenticate|session[s]?\/new|mfa|otp|2fa|verify|ログイン|サインイン)(\/|$)/i;

/** 認証壁を検知した層。返却物には出さない（呼び出し側の分岐材料にならない）が、`--verbose` で見える。 */
export type AuthLayer = 'input' | 'navigation' | 'observation';

export interface AuthWall {
  layer: AuthLayer;
  /**
   * 最終 URL の**ホスト部分だけ**。返却物に載せてよいページ由来情報はこれが上限で、
   * パス・クエリ・タイトル・フォーム項目名は載せない。「デバッグに便利だから」で緩めない。
   */
  host?: string;
}

/**
 * URL からホストだけを取り出す。パス・クエリ・フラグメントは**ここで捨てる**。
 * URL として読めなければ `undefined`（読めない文字列をそのまま返すと本文が混じりうる）。
 */
export function hostOf(url: string | undefined): string | undefined {
  if (!url)
    return undefined;
  try {
    return new URL(url).host || undefined;
  } catch {
    return undefined;
  }
}

/**
 * 入力層。`fill` の対象ラベル（`textbox「パスワード」` の形）が資格情報を示すか。
 *
 * `<input type="password">` は ARIA に専用のロールが無く、snapshot では普通の textbox として出る。
 * **型では見分けられないので名前で見る。** そのぶん取りこぼすが、取りこぼしは遷移層・観測層が拾う。
 */
export function isCredentialLabel(label: string): boolean {
  return CREDENTIAL_WORD.test(label);
}

/** 遷移層。現在地が認証ドメイン、またはログインらしきパスか。 */
export function isAuthUrl(url: string | undefined): boolean {
  if (!url)
    return false;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (AUTH_HOST.test(parsed.host))
    return true;
  return AUTH_PATH.test(parsed.pathname.replace(/\.[a-z0-9]+$/i, ''));
}

/** ダイジェストの ref 表の行（`| e5 | textbox | パスワード |`）。 */
const REF_ROW = /^\|\s*(?:f\d+)?e\d+\s*\|([^|]*)\|([^|]*)\|\s*$/;
/** pwq が素通しした生 aria snapshot の行（`- textbox "パスワード"`）。 */
const YAML_NODE = /^\s*-\s*([a-z]+)(?:\s+"([^"]*)")?/;
/** 値を打ち込めるロール。ここに限るのは「パスワードをお忘れですか」リンクで誤爆しないため。 */
const INPUT_ROLE = /^(textbox|searchbox|combobox|spinbutton|input)$/i;

/**
 * 観測層。観測結果に資格情報の入力欄が含まれるか。
 *
 * **ロールと名前の両方**を見る。名前だけで判定すると「パスワードをお忘れですか」のリンクを持つ
 * 普通のページで止まってしまい、誤爆のコストが検知の利得を上回る。
 */
export function snapshotHasCredentialField(text: string): boolean {
  for (const line of text.split('\n')) {
    const row = line.match(REF_ROW);
    if (row) {
      if (INPUT_ROLE.test(row[1].trim()) && CREDENTIAL_WORD.test(row[2]))
        return true;
      continue;
    }
    const node = line.match(YAML_NODE);
    if (node && INPUT_ROLE.test(node[1]) && CREDENTIAL_WORD.test(node[2] ?? ''))
      return true;
  }
  return false;
}

/**
 * 認証壁に当たったので委譲を打ち切る、という合図。
 *
 * **メッセージにページ由来の情報を入れない。** これは AI SDK 経由でモデルへ渡りうる文字列で、
 * そのまま `summary` に引用されると返却物へ漏れる。ホストは {@link AuthWall} 側だけが持つ。
 */
export class AuthWallError extends Error {
  readonly wall: AuthWall;

  constructor(wall: AuthWall) {
    super('認証が必要な画面に到達したため、委譲を中断しました。');
    this.name = 'AuthWallError';
    this.wall = wall;
  }
}

/* ------------------------------------------------------------------ *
 * 範囲（URL 許可リスト）
 *
 * 委譲の本来の用途は「**今いるサイトでの一区間**」。外部への遷移が要るシナリオは
 * `--allow` で明示させ、**既定は「現在のオリジンと同一」**にする。
 * 既定を「何でも可」にしない —— 実サイトはリンク 1 つで SSO・外部決済・広告ドメインへ飛ぶので、
 * 既定が緩いと外向きの防壁が認証ガード 1 枚だけになる。
 * ------------------------------------------------------------------ */

/**
 * 許可範囲。`origins` は委譲開始時点のオリジン（**最初の観測で確定する**。
 * 委譲前にページ URL を知る手段を増やしたくないため）、`hosts` は `--allow` で明示されたもの。
 */
export interface UrlPolicy {
  /** `scheme://host[:port]` の集合。既定はここに現在地のオリジンが 1 つだけ入る */
  readonly origins: Set<string>;
  /** `--allow` で明示されたホスト。先頭が `.` なら下位ドメインも含む */
  readonly hosts: string[];
  /** `--allow=*`。**明示したときだけ**立つ */
  readonly any: boolean;
}

export function createUrlPolicy(allow: string[]): UrlPolicy {
  const hosts: string[] = [];
  let any = false;
  for (const raw of allow) {
    const entry = raw.trim();
    if (!entry)
      continue;
    if (entry === '*') {
      any = true;
      continue;
    }
    // `https://example.com/path` でも `example.com` でも受ける。比較はホストだけで行う。
    const host = hostOf(entry) ?? hostOf(`http://${entry}`) ?? entry;
    hosts.push(host.toLowerCase());
  }
  return { origins: new Set<string>(), hosts, any };
}

/** 現在地のオリジンを覚える。**最初の 1 回だけ**効く（途中の遷移で範囲が広がらない）。 */
export function noteOrigin(policy: UrlPolicy, url: string | undefined): void {
  if (!url || policy.origins.size)
    return;
  try {
    policy.origins.add(new URL(url).origin);
  } catch {
    // URL として読めないなら覚えない。次の観測で拾い直す。
  }
}

/**
 * `navigate` の引数を絶対 URL にする。`back` / `reload` はここへ来ない。
 * 相対パスは現在地から解決する（`/cart` のような指定が実際に来る）。
 */
export function resolveTarget(to: string, baseUrl: string | undefined): string | undefined {
  try {
    return new URL(to, baseUrl).toString();
  } catch {
    return undefined;
  }
}

/** ホストが `--allow` の 1 件に当たるか。`.example.com` は下位ドメインも含む。 */
function hostAllowed(host: string, entry: string): boolean {
  if (entry.startsWith('.'))
    return host === entry.slice(1) || host.endsWith(entry);
  return host === entry;
}

/** 許可範囲の中か。判定はオリジン一致（scheme + host + port）と `--allow` のホスト一致の 2 本だけ。 */
export function isAllowedUrl(target: string, policy: UrlPolicy): boolean {
  if (policy.any)
    return true;
  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return false;
  }
  if (policy.origins.has(parsed.origin))
    return true;
  const host = parsed.host.toLowerCase();
  return policy.hosts.some(entry => hostAllowed(host, entry));
}

/** 否認理由に載せる許可範囲。**ホストまで**で、パスは載せない。 */
export function describePolicy(policy: UrlPolicy): string {
  if (policy.any)
    return '（すべて許可）';
  const parts = [...policy.origins, ...policy.hosts];
  return parts.length ? parts.join(', ') : '（まだ現在地を観測していません）';
}

/* ------------------------------------------------------------------ *
 * 不可逆操作の停止語
 *
 * **停止語だけでは必ず漏れる。** サイトごとに確定ボタンの文言が違うので、
 * モデル自身の申告（`confirm_needed`）と併用して二重にする。片方だけにしない。
 * 誤って止まる側に倒してある —— 止まっても生きたセッションが呼び出し側へ返るだけで、
 * 壊れるものは無い（逆は取り返しがつかない）。
 * ------------------------------------------------------------------ */

/**
 * 日本語の停止語。**確定・購入・削除・送信**の 4 系統。
 * 「カートに入れる」「次へ」「レジへ進む」は入れない —— 引き返せる操作で、
 * ここで止めると委譲がレジ前まで一度も通らなくなる。
 */
const IRREVERSIBLE_JA =
  /(注文(を)?(確定|確認|する)|購入(を)?(確定|する)|決済|支払(う|いを確定|いを完了)|申し込(む|みを確定)|予約(を)?(確定|する)|送信|投稿|公開|削除|消去|退会|解約|キャンセル(する|を確定)|送金|振込|振替|確定する|アーカイブ(する|にする)|無効(化|にする)|失効)/;

/**
 * 英語の停止語。単語境界で当てる —— `\bpay\b` を接頭辞照合にすると `payment method` の
 * ラジオボタンで止まる。`checkout` は入れない（レジ**へ進む**操作で引き返せる）。
 */
const IRREVERSIBLE_EN =
  /\b(place (the )?order|confirm (and )?(order|purchase|payment|booking|delete|deletion)|buy( it)?( now)?|purchase|pay( now)?|submit|send|post|publish|delete|remove|erase|destroy|deactivate|unsubscribe|cancel (my )?(subscription|order|booking|account)|transfer|withdraw|revoke|archive (this|the)\b|disable [\w\s]*(protection|rule|policy|2fa|two-factor|security)|leave (this |the )?(repository|organization|organisation|team|workspace))\b/i;

/**
 * この見出し（`ボタン「注文を確定する」` の形）の操作を不可逆とみなすか。
 *
 * 判定は**見出しの文字列だけ**で行う。`href` や DOM の属性は見ない —— 見るには観測を深くする必要があり、
 * 委譲先へ渡す情報量を増やす（それ自体が pwdo の価値を削る）。
 */
export function isIrreversibleLabel(label: string): boolean {
  return IRREVERSIBLE_JA.test(label) || IRREVERSIBLE_EN.test(label);
}
