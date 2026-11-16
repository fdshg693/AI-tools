import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { PwqError, resolveLauncher, runCli, runCliInherit, type CliLauncher } from './passthrough.js';
import {
  findSection, hasError, inlineSnapshot, parseOutput, parsePageSection,
  snapshotLink, stripFence, type ParsedOutput,
} from './parse.js';
import { Store, countLines, resolveSessionName, type ArtifactEntry } from './store.js';
import { digestSnapshot } from './digest.js';
import { renderResultDigest, renderSnapshotDigest } from './render.js';
import {
  answerFor, missingTargetMessage, parseOwnFlags, resolveTarget, runHistory, runModels,
  type OwnFlags,
} from './llm-commands.js';
import { DEFAULT_MAX_CHARS, DEFAULT_MAX_HISTORY } from './ask.js';
import { readPackageVersion } from './config.js';


/** これ以下なら横取りしない（往復が増える方が高くつく） */
const DEFAULT_THRESHOLD = 2048;
const DEFAULT_MAX_REFS = 60;
const DEFAULT_MAX_OUTLINE = 40;
const DEFAULT_HEAD_LINES = 15;
const HEAD_COLUMNS = 200;

/** 出力を溜めずに素通しすべきコマンド（対話・長時間・進捗表示） */
const INHERIT_COMMANDS = new Set([
  'show', 'pause-at', 'resume', 'step-over', 'install', 'install-browser',
  'recording-start', 'recording-stop', 'video-start', 'video-stop',
]);

interface PwqOptions {
  help: boolean;
  aiHelp: boolean;
  version: boolean;
  off: boolean;
  threshold: number;
  maxRefs: number;
  maxOutline: number;
  headLines: number;
  store?: string;
  /** 通常コマンドの出力に LLM の要約を足す（既定では LLM を呼ばない） */
  summarize: boolean;
  model?: string;
  cost: boolean;
  maxChars: number;
  maxHistory: number;
}

/** pwq 自身のサブコマンド（playwright-cli 側に同名は無い） */
const OWN_COMMANDS = new Set(['cache', 'ask', 'summarize', 'explore', 'history', 'steps', 'models']);

interface SplitArgs {
  pwq: PwqOptions;
  downstream: string[];
}

/**
 * `pwq` 自身のオプションは `--pwq-` 接頭辞でのみ受ける。
 * それ以外は一切解釈せず playwright-cli へ素通しする（上流でオプションが増えても衝突しないため）。
 */
export function splitArgs(argv: string[]): SplitArgs {
  const pwq: PwqOptions = {
    help: false,
    aiHelp: false,
    version: false,
    off: false,
    threshold: DEFAULT_THRESHOLD,
    maxRefs: DEFAULT_MAX_REFS,
    maxOutline: DEFAULT_MAX_OUTLINE,
    headLines: DEFAULT_HEAD_LINES,
    summarize: false,
    cost: false,
    maxChars: DEFAULT_MAX_CHARS,
    maxHistory: DEFAULT_MAX_HISTORY,
  };
  const downstream: string[] = [];

  for (const arg of argv) {
    if (!arg.startsWith('--pwq-')) {
      downstream.push(arg);
      continue;
    }
    const eq = arg.indexOf('=');
    const name = eq === -1 ? arg.slice(6) : arg.slice(6, eq);
    const value = eq === -1 ? undefined : arg.slice(eq + 1);
    switch (name) {
      case 'help': pwq.help = true; break;
      case 'ai-help': pwq.aiHelp = true; break;
      case 'version': pwq.version = true; break;
      case 'off': pwq.off = true; break;
      case 'store': pwq.store = requireValue(arg, value); break;
      case 'summarize': pwq.summarize = true; break;
      case 'cost': pwq.cost = true; break;
      case 'model': pwq.model = requireValue(arg, value); break;
      case 'max-chars': pwq.maxChars = requireNumber(arg, value); break;
      case 'max-history': pwq.maxHistory = requireNumber(arg, value); break;
      case 'threshold': pwq.threshold = requireNumber(arg, value); break;
      case 'max-refs': pwq.maxRefs = requireNumber(arg, value); break;
      case 'max-outline': pwq.maxOutline = requireNumber(arg, value); break;
      case 'head-lines': pwq.headLines = requireNumber(arg, value); break;
      default:
        throw new PwqError(`不明な pwq オプション: ${arg}\n\`pwq --pwq-help\` を見てください。`);
    }
  }
  return { pwq, downstream };
}

function requireValue(arg: string, value?: string): string {
  if (value === undefined || value === '')
    throw new PwqError(`${arg} には値が必要です（例: ${arg.split('=')[0]}=値）`);
  return value;
}

function requireNumber(arg: string, value?: string): number {
  const n = Number(requireValue(arg, value));
  if (!Number.isInteger(n) || n < 0)
    throw new PwqError(`${arg} には 0 以上の整数を指定してください`);
  return n;
}

interface Downstream {
  command?: string;
  session?: string;
  json: boolean;
  raw: boolean;
  help: boolean;
  version: boolean;
  hasFilename: boolean;
}

/**
 * playwright-cli 側のグローバルオプションだけを「読む」。消費はしない。
 * `-s foo` / `--session foo` の空白形は minimist が値として食うので、こちらも 1 つ読み飛ばす。
 */
export function inspectDownstream(args: string[]): Downstream {
  const out: Downstream = { json: false, raw: false, help: false, version: false, hasFilename: false };
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (!arg.startsWith('-')) {
      if (out.command === undefined)
        out.command = arg;
      continue;
    }
    const eq = arg.indexOf('=');
    const name = eq === -1 ? arg : arg.slice(0, eq);
    const inlineValue = eq === -1 ? undefined : arg.slice(eq + 1);
    switch (name) {
      case '-s':
      case '--session':
        out.session = inlineValue ?? args[++i];
        break;
      case '--filename':
        out.hasFilename = true;
        if (inlineValue === undefined)
          i++;
        break;
      case '--json': out.json = true; break;
      case '--raw': out.raw = true; break;
      case '--help': case '-h': out.help = true; break;
      case '--version': case '-v': out.version = true; break;
      default: break;
    }
  }
  return out;
}

function printHelp(): void {
  console.log(`pwq - playwright-cli のコンテキスト節約ラッパー

使い方:
  pwq <playwright-cli の引数そのまま>
  pwq cache list | show <id> | path <id>
  pwq explore <url>            開いて + ダイジェスト + 初期要約（LLM を 1 回呼ぶ）
  pwq summarize [--step <id>]  キャッシュ済み snapshot の要約（履歴に残さない）
  pwq ask "<質問>" [--step <id>]  同じ snapshot への質問。ブラウザは操作しない
  pwq history                  ストアの一覧と Q&A 往復数（LLM 不要）
  pwq models                   モデル一覧と鍵の解決状況（LLM 不要）

playwright-cli の引数は一切解釈せずそのまま渡します。違うのは出力の後処理だけで、
巨大な snapshot / eval 結果をローカルのストアへ逃がし、
標準出力には「ページ状態 + 機械抽出した ref 表 + キャッシュハンドル」を返します。

pwq 自身のオプション（すべて --pwq- 接頭辞。これ以外は下流へ素通し）:
  --pwq-help                 このヘルプ
  --pwq-ai-help              エージェント向けの使い方（モデル一覧・鍵の状態つき）
  --version / --pwq-version  pwq のバージョン（playwright-cli へは渡しません）
  --pwq-summarize            通常コマンドの出力に LLM の要約を足す（既定は呼ばない）
  --pwq-model=<alias>        使うモデル（\`pwq models\` で一覧）
  --pwq-cost                 概算コストも出す（OpenRouter Models API を 1 回叩く）
  --pwq-max-chars=<n>        LLM に渡す snapshot の最大文字数（既定: ${DEFAULT_MAX_CHARS}）
  --pwq-max-history=<n>      引き継ぐ Q&A の往復数（既定: ${DEFAULT_MAX_HISTORY}）
  --pwq-off                  横取りを無効化（完全な素通し）
  --pwq-threshold=<bytes>    これ以下なら横取りしない（既定: ${DEFAULT_THRESHOLD}）
  --pwq-max-refs=<n>         ref 表の最大行数（既定: ${DEFAULT_MAX_REFS}）
  --pwq-max-outline=<n>      構造アウトラインの最大行数（既定: ${DEFAULT_MAX_OUTLINE}）
  --pwq-head-lines=<n>       結果テキストの先頭表示行数（既定: ${DEFAULT_HEAD_LINES}）
  --pwq-store=<dir>          ストアのルート（既定: <git ルート>/.playwright-cli/pwq。相対は cwd 基準）

横取りしない条件:
  --raw / --json / --help / -v が付いているとき（生出力を明示的に求めている経路）
  エラー時（stderr と終了コードはそのまま透過。加工するとデバッグ不能になる）

ask / summarize / explore の素のフラグ（下流へは渡らない経路なので接頭辞不要）:
  --step=<id>                対象のキャッシュ（既定: 最新の snapshot）
  --model=<alias> / -m       使うモデル
  --fresh                    この snapshot の Q&A 履歴を捨てて聞き直す
  --no-refs                  検証済み ref の一覧を出さない（散文だけ）
  --cost                     概算コストも出す
  --max-chars=<n> / --max-history=<n>

環境変数:
  PWQ_PLAYWRIGHT_CLI         playwright-cli の実体（playwright-cli.js 等）のパス
  PLAYWRIGHT_CLI_SESSION     セッション名（playwright-cli と共通）
  OPENROUTER_API_KEY         LLM 層の鍵。無ければ LLM 層だけスキップして続行する
                             （ツール直下の .env を 1 か所だけ見る）

注意:
  ref（eNN）の正はキャッシュした snapshot だけです。ダイジェストの ref 表は機械抽出であり、
  補完も推測もしません。ページ遷移をまたぐと ref には前置きが付く（e13 → f2e13）ので、
  古い ref を使い回さず、遷移後は取り直してください。`);
}

function makeStore(cwd: string, downstream: Downstream, pwq: PwqOptions): Store {
  return new Store(cwd, resolveSessionName(downstream.session), pwq.store);
}

/** pwq 自身のサブコマンド。playwright-cli に `cache` は無いので衝突しない。 */
async function runCacheCommand(args: string[], pwq: PwqOptions, cwd: string): Promise<number> {
  const downstream = inspectDownstream(args);
  const store = makeStore(cwd, downstream, pwq);
  const positionals = args.filter(a => !a.startsWith('-'));
  const sub = positionals[1];
  const id = positionals[2];

  if (sub === 'list' || sub === undefined) {
    const entries = store.entries();
    if (!entries.length) {
      console.log(`（ストアは空です: ${store.displayPath(store.dir, cwd)}）`);
      return 0;
    }
    console.log(`session: ${store.session}  dir: ${store.displayPath(store.dir, cwd)}`);
    console.log('| id | kind | bytes | lines | command | url |');
    console.log('| --- | --- | ---: | ---: | --- | --- |');
    for (const e of entries)
      console.log(`| ${e.id} | ${e.kind} | ${e.bytes} | ${e.lines} | ${e.command} | ${e.url ?? ''} |`);
    return 0;
  }

  if (sub === 'show' || sub === 'path') {
    const entry = resolveEntry(store, id);
    if (!entry) {
      console.error(`キャッシュが見つかりません: ${id ?? '(latest)'}（\`pwq cache list\` で確認してください）`);
      return 1;
    }
    if (sub === 'path') {
      console.log(entry.file);
      return 0;
    }
    const range = args.map(a => a.match(/^--lines=(\d+)-(\d+)$/)).find(Boolean);
    let text = fs.readFileSync(entry.file, 'utf-8');
    if (range) {
      const lines = text.split('\n');
      text = lines.slice(Number(range[1]) - 1, Number(range[2])).join('\n');
    }
    process.stdout.write(text.endsWith('\n') ? text : text + '\n');
    return 0;
  }

  console.error(`不明なサブコマンド: pwq cache ${sub}\n使えるのは list / show / path です。`);
  return 1;
}

function resolveEntry(store: Store, id?: string): ArtifactEntry | undefined {
  if (!id || id === 'latest')
    return store.latest();
  return store.get(id);
}

/** Snapshot 以外のセクションはそのまま持ち回す（Ran Playwright code / Events / Modal state 等） */
function otherSections(parsed: ParsedOutput, exclude: string[]): { name: string; body: string }[] {
  return parsed.sections.filter(s => !exclude.includes(s.name));
}

/** 素通しコマンドでも [Snapshot](...) だけは拾ってストアに登録する（後続の `pwq ask` の対象） */
function registerLinkedSnapshot(
  store: Store, parsed: ParsedOutput, cwd: string, command: string, argv: string[]
): ArtifactEntry | undefined {
  const file = snapshotLink(parsed, cwd);
  if (!file)
    return undefined;
  let text: string;
  try {
    text = fs.readFileSync(file, 'utf-8');
  } catch {
    return undefined;
  }
  const page = parsePageSection(parsed);
  const { id } = store.reserve('snapshot', '.yml');
  const entry: ArtifactEntry = {
    id, kind: 'snapshot', file, command, argv,
    bytes: Buffer.byteLength(text, 'utf-8'), lines: countLines(text),
    url: page.url, title: page.title, createdAt: new Date().toISOString(),
  };
  store.record(entry);
  return entry;
}

/**
 * 実行結果。`entry` は「LLM 層が続けて要約できるもの」がストアに入ったときだけ入る。
 * ② 層（要約）を足すかは呼び出し側（main）が決める。
 */
interface RunOutcome {
  code: number;
  store?: Store;
  entry?: ArtifactEntry;
}

/** `snapshot` に --filename を注入してファイル化させ、リンクを自前のダイジェストに差し替える */
async function runSnapshot(
  launcher: CliLauncher, args: string[], pwq: PwqOptions, downstream: Downstream, cwd: string
): Promise<RunOutcome> {
  const store = makeStore(cwd, downstream, pwq);
  const { id, file } = store.reserve('snapshot', '.yml');
  fs.mkdirSync(path.dirname(file), { recursive: true });

  const result = await runCli(launcher, [...args, `--filename=${file}`], cwd);
  if (result.stderr)
    process.stderr.write(result.stderr);

  const parsed = parseOutput(result.stdout);
  if (result.code !== 0 || hasError(parsed)) {
    process.stdout.write(result.stdout);
    return { code: result.code };
  }

  let yaml: string;
  try {
    yaml = fs.readFileSync(file, 'utf-8');
  } catch {
    // ファイル化に失敗したなら加工せず原文を出す
    process.stdout.write(result.stdout);
    return { code: result.code };
  }

  const page = parsePageSection(parsed);
  const entry: ArtifactEntry = {
    id, kind: 'snapshot', file, command: 'snapshot', argv: args,
    bytes: Buffer.byteLength(yaml, 'utf-8'), lines: countLines(yaml),
    url: page.url, title: page.title, createdAt: new Date().toISOString(),
  };
  store.record(entry);

  const rest = otherSections(parsed, ['Page', 'Snapshot']);

  if (entry.bytes <= pwq.threshold) {
    // 小さい snapshot は横取りしない方が往復が減って安い。素の出力の形に戻して出す。
    const lines: string[] = [];
    if (parsed.preamble)
      lines.push(parsed.preamble.replace(/\n+$/, ''));
    const pageSection = findSection(parsed, 'Page');
    if (pageSection)
      lines.push('### Page', pageSection.body);
    lines.push('### Snapshot', '```yaml', yaml.replace(/\n+$/, ''), '```');
    for (const s of rest)
      lines.push(`### ${s.name}`, s.body);
    lines.push(`(pwq: cached as \`${id}\` — ${store.displayPath(file, cwd)})`);
    console.log(lines.join('\n'));
    return { code: result.code, store, entry };
  }

  console.log(renderSnapshotDigest({
    entry,
    displayFile: store.displayPath(file, cwd),
    digest: digestSnapshot(yaml),
    page,
    maxRefs: pwq.maxRefs,
    maxOutline: pwq.maxOutline,
    otherSections: rest,
  }));
  return { code: result.code, store, entry };
}

/** それ以外のコマンド: stdout を読み切り、閾値を超えたときだけ一番大きいセクションを逃がす */
async function runCaptured(
  launcher: CliLauncher, args: string[], pwq: PwqOptions, downstream: Downstream, cwd: string
): Promise<RunOutcome> {
  const command = downstream.command!;
  const result = await runCli(launcher, args, cwd);
  if (result.stderr)
    process.stderr.write(result.stderr);

  const parsed = parseOutput(result.stdout);
  const failed = result.code !== 0 || hasError(parsed);

  if (failed || Buffer.byteLength(result.stdout, 'utf-8') <= pwq.threshold) {
    process.stdout.write(result.stdout);
    if (!failed) {
      const store = makeStore(cwd, downstream, pwq);
      const entry = registerLinkedSnapshot(store, parsed, cwd, command, args);
      return { code: result.code, store, entry };
    }
    return { code: result.code };
  }

  const store = makeStore(cwd, downstream, pwq);
  const page = parsePageSection(parsed);

  // インライン snapshot があればそれが最大の犯人
  const yaml = inlineSnapshot(parsed);
  if (yaml !== undefined) {
    const { id, file } = store.reserve('snapshot', '.yml');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, yaml.endsWith('\n') ? yaml : yaml + '\n', 'utf-8');
    const entry: ArtifactEntry = {
      id, kind: 'snapshot', file, command, argv: args,
      bytes: Buffer.byteLength(yaml, 'utf-8'), lines: countLines(yaml),
      url: page.url, title: page.title, createdAt: new Date().toISOString(),
    };
    store.record(entry);
    console.log(renderSnapshotDigest({
      entry,
      displayFile: store.displayPath(file, cwd),
      digest: digestSnapshot(yaml),
      page,
      maxRefs: pwq.maxRefs,
      maxOutline: pwq.maxOutline,
      otherSections: otherSections(parsed, ['Page', 'Snapshot']),
    }));
    return { code: result.code, store, entry };
  }

  // それ以外は一番バイト数の大きいセクションを逃がす（eval / run-code / response-body 等）
  const biggest = [...parsed.sections].sort(
    (a, b) => Buffer.byteLength(b.body, 'utf-8') - Buffer.byteLength(a.body, 'utf-8')
  )[0];
  if (!biggest) {
    process.stdout.write(result.stdout);
    return { code: result.code };
  }

  const text = stripFence(biggest.body);
  const { id, file } = store.reserve('result', '.txt');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text.endsWith('\n') ? text : text + '\n', 'utf-8');
  const entry: ArtifactEntry = {
    id, kind: 'result', file, command, argv: args,
    bytes: Buffer.byteLength(text, 'utf-8'), lines: countLines(text),
    url: page.url, title: page.title, createdAt: new Date().toISOString(),
  };
  store.record(entry);

  console.log(renderResultDigest({
    entry,
    displayFile: store.displayPath(file, cwd),
    sectionName: biggest.name,
    text,
    headLines: pwq.headLines,
    headColumns: HEAD_COLUMNS,
    otherSections: otherSections(parsed, [biggest.name]),
    preamble: parsed.preamble,
  }));
  return { code: result.code, store, entry };
}

/** `--pwq-*` と素のフラグを混ぜて受けるための合成（素のフラグが優先） */
function mergeFlags(pwq: PwqOptions, own: OwnFlags, cwd: string) {
  return {
    ...own,
    cwd,
    model: own.model ?? pwq.model,
    cost: own.cost || pwq.cost,
    maxChars: own.maxChars !== DEFAULT_MAX_CHARS ? own.maxChars : pwq.maxChars,
    maxHistory: own.maxHistory !== DEFAULT_MAX_HISTORY ? own.maxHistory : pwq.maxHistory,
  };
}

/** `ask` / `summarize`: ブラウザには一切触らず、キャッシュ済みアーティファクトだけを見る */
async function runAskCommand(
  args: string[], pwq: PwqOptions, cwd: string, mode: 'ask' | 'summarize'
): Promise<number> {
  const info = inspectDownstream(args);
  const store = makeStore(cwd, info, pwq);
  const own = parseOwnFlags(args);
  const entry = resolveTarget(store, own.step);
  if (!entry) {
    console.error(missingTargetMessage(store, own.step));
    return 1;
  }
  if (mode === 'ask' && !own.question) {
    console.error('質問がありません。例: pwq ask "この表の列は何か"');
    return 1;
  }
  const { text, ok } = await answerFor(
    store, entry, mode === 'ask' ? own.question : undefined, mergeFlags(pwq, own, cwd)
  );
  console.log(text);
  return ok ? 0 : 1;
}

/**
 * `explore <url>`: goto してダイジェスト + 初期要約までを 1 コマンドで返す。
 * goto が書き出した snapshot ファイルをそのまま使うので、ブラウザは 1 往復しかしない。
 */
async function runExplore(
  launcher: CliLauncher, args: string[], pwq: PwqOptions, cwd: string
): Promise<number> {
  const own = parseOwnFlags(args);
  const url = own.positionals[1];
  if (!url) {
    console.error('URL がありません。例: pwq explore http://localhost:8080/tables/');
    return 1;
  }
  const info = inspectDownstream(args);
  const common = [...(info.session ? ['--session', info.session] : []), ...own.rest];

  // ブラウザが未起動なら goto は使えない。まず goto を試し、未起動なら open に落とす。
  let downstreamArgs = ['goto', url, ...common];
  let result = await runCli(launcher, downstreamArgs, cwd);
  if (result.code !== 0 && /not open/.test(result.stdout + result.stderr)) {
    downstreamArgs = ['open', url, ...common];
    result = await runCli(launcher, downstreamArgs, cwd);
  }

  if (result.stderr)
    process.stderr.write(result.stderr);
  const parsed = parseOutput(result.stdout);
  if (result.code !== 0 || hasError(parsed)) {
    process.stdout.write(result.stdout);
    return result.code;
  }

  const store = makeStore(cwd, info, pwq);
  const entry = registerLinkedSnapshot(store, parsed, cwd, downstreamArgs[0], downstreamArgs);
  if (!entry) {
    // snapshot が付いてこなかった（想定外）。原文を出して終わる
    process.stdout.write(result.stdout);
    return result.code;
  }

  const yaml = fs.readFileSync(entry.file, 'utf-8');
  console.log(renderSnapshotDigest({
    entry,
    displayFile: store.displayPath(entry.file, cwd),
    digest: digestSnapshot(yaml),
    page: { url: entry.url, title: entry.title },
    maxRefs: pwq.maxRefs,
    maxOutline: pwq.maxOutline,
    otherSections: otherSections(parsed, ['Page', 'Snapshot']),
  }));

  const { text } = await answerFor(store, entry, undefined, mergeFlags(pwq, own, cwd));
  console.log('');
  console.log(text);
  return result.code;
}

function printAiHelp(): void {
  console.log(`pwq — playwright-cli の出力をローカルにキャッシュし、要約だけを返すラッパー。

いつ使うか:
  初めて見るページを調べるとき。snapshot / eval の生出力をコンテキストに流し込まない。
いつ使わないか:
  出力を機械処理するとき（--json / --raw）と、既に ref が分かっていて操作するだけのとき。
  操作コマンド（click / fill / goto）は pwq を通しても LLM を呼ばないので、通しても損はない。

典型的な流れ（LLM 呼び出しは 1 回だけ）:
  pwq explore <url>            # 開く + ref 表 + 初期要約
  pwq ask "<質問>"             # 同じ snapshot に追加質問。ブラウザは動かない・再取得しない
  pwq ask "<別の質問>"         # 何度でも。履歴は自動で引き継ぐ
  pwq click <ref>              # ref はダイジェストの表 / 検証済み ref から取る
  pwq snapshot                 # 遷移したら取り直す（ref には前置きが付く）

ref の信頼性:
  ダイジェストの ref 表は snapshot からの機械抽出。モデルの散文に現れた ref は
  ストアの ref 集合と突き合わせて検証し、存在しないものには警告を出す。
  警告が付いた ref は使わないこと。

生データへの到達手段（ラッパーは塞がない）:
  pwq cache list / pwq cache show <id> [--lines=A-B] / pwq cache path <id>
  playwright-cli find "<text>"

LLM を呼ぶコマンド: explore / summarize / ask、および --pwq-summarize 付きの実行だけ。
鍵（OPENROUTER_API_KEY）が無い場合は LLM 層だけスキップし、ダイジェストは通常どおり出る。
`);
  runModels();
}

export async function main(argv = process.argv.slice(2)): Promise<number> {
  // `--version` は pwq 自身の版数（tool-conventions の --version 契約）。playwright-cli の版数は `-v` で素通し。
  if (argv.includes('--version')) {
    console.log(`pwq ${readPackageVersion()}`);
    return 0;
  }
  const { pwq, downstream: args } = splitArgs(argv);

  if (pwq.version) {
    console.log(`pwq ${readPackageVersion()}`);
    return 0;
  }
  if (pwq.aiHelp) {
    printAiHelp();
    return 0;
  }
  if (pwq.help || (!args.length && !pwq.off)) {
    printHelp();
    return 0;
  }

  const cwd = process.cwd();
  const info = inspectDownstream(args);

  // pwq 自身のサブコマンド（ブラウザを起動しないものが先）
  if (info.command && OWN_COMMANDS.has(info.command)) {
    switch (info.command) {
      case 'cache':
        return runCacheCommand(args, pwq, cwd);
      case 'history': case 'steps':
        return runHistory(makeStore(cwd, info, pwq), cwd);
      case 'models':
        return runModels();
      case 'ask':
        return runAskCommand(args, pwq, cwd, 'ask');
      case 'summarize':
        return runAskCommand(args, pwq, cwd, 'summarize');
      case 'explore':
        return runExplore(resolveLauncher(), args, pwq, cwd);
    }
  }

  const launcher = resolveLauncher();

  // 明示的に生出力を求めている経路 / 短い経路は完全素通し
  if (pwq.off || info.raw || info.json || info.help || info.version ||
      !info.command || INHERIT_COMMANDS.has(info.command))
    return runCliInherit(launcher, args, cwd);

  const outcome = info.command === 'snapshot' && !info.hasFilename
    ? await runSnapshot(launcher, args, pwq, info, cwd)
    : await runCaptured(launcher, args, pwq, info, cwd);

  // 通常コマンドで LLM を呼ぶのは --pwq-summarize を明示したときだけ
  if (pwq.summarize && outcome.store && outcome.entry) {
    const { text } = await answerFor(
      outcome.store, outcome.entry, undefined,
      mergeFlags(pwq, parseOwnFlags([], 0), cwd)
    );
    console.log('');
    console.log(text);
  }
  return outcome.code;
}

main()
  .then(code => { process.exitCode = code; })
  .catch(err => {
    console.error(err instanceof Error ? err.message : String(err));
    process.exitCode = 1;
  });
