import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

/**
 * 実行層。`playwright-cli` と `pwq` を **子プロセスとして** 起動する。
 *
 * `pwq/src/passthrough.ts` から形を借りている（Windows の `.cmd` シム回避で同じ問題を踏むため）。
 * 違いは 3 点:
 *  - 起動先が 2 つある（`playwright-cli` と `pwq`）
 *  - 素通し（`stdio: 'inherit'`）の経路を持たない。pwdo の stdout は report.ts が組み立てたものだけ
 *  - コマンドのホワイトリストを持つ。`open` / `close` / `eval` などはここで止まる
 */

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, '..');

export class PwdoError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PwdoError';
  }
}

export interface CliLauncher {
  /** 実行ファイル（node 自身 or シェル不要の実行可能ファイル） */
  command: string;
  /** 引数の前置き（node で .js を起動する場合の js パス等） */
  prefixArgs: string[];
  /** 人間向けの説明（エラーメッセージ用） */
  label: string;
}

const PLAYWRIGHT_CLI_HINT = [
  'playwright-cli が見つかりません。',
  '',
  '  npm install -g @playwright/cli     # または pnpm add -g @playwright/cli',
  '  npx playwright cli --version       # 一時利用',
  '',
  'すでに入っている場合は PWDO_PLAYWRIGHT_CLI に実体（playwright-cli.js のパス、',
  'もしくはシェル不要な実行ファイルのパス）を指定してください。',
].join('\n');

const PWQ_HINT = [
  'pwq が見つかりません。',
  '',
  '  cd tools/browser/pwq && pnpm build && pnpm add -g .   # アンブレラのルートで pnpm install 済みの前提',
  '',
  '別の場所にある場合は PWDO_PWQ に dist/cli.js のパスを指定してください。',
].join('\n');

function pathExtCandidates(): string[] {
  if (process.platform !== 'win32')
    return [''];
  const pathext = process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD';
  return pathext.split(';').filter(Boolean);
}

/** PATH と PATHEXT を自前で走査する。Node の spawn は win32 で .cmd を直接起動できないため。 */
export function findOnPath(name: string): string | undefined {
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const exts = pathExtCandidates();
  for (const dir of dirs) {
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext);
      try {
        if (fs.statSync(candidate).isFile())
          return candidate;
      } catch {
        // 次の候補へ
      }
    }
  }
  return undefined;
}

/**
 * npm / pnpm が生成する Windows の .cmd シムから、実体の JS パスを取り出す。
 * シムはパスを二重引用符で埋め込んでいる（`%~dp0` 起点の相対）。
 */
export function extractJsFromCmdShim(shimPath: string): string | undefined {
  let text: string;
  try {
    text = fs.readFileSync(shimPath, 'utf-8');
  } catch {
    return undefined;
  }
  const shimDir = path.dirname(shimPath);
  const re = /"([^"\n]*?\.(?:js|mjs|cjs))"/g;
  for (const m of text.matchAll(re)) {
    // %~dp0 / %dp0% は末尾にセパレータを含むので、そのまま join せず置換してから正規化する
    const raw = m[1].replace(/%~?dp0%?/gi, shimDir + path.sep).replace(/\\/g, path.sep);
    const resolved = path.normalize(raw);
    try {
      if (fs.statSync(resolved).isFile())
        return resolved;
    } catch {
      // 次の候補へ
    }
  }
  return undefined;
}

function launcherForFile(file: string, label: string): CliLauncher | undefined {
  const ext = path.extname(file).toLowerCase();
  if (ext === '.js' || ext === '.mjs' || ext === '.cjs')
    return { command: process.execPath, prefixArgs: [file], label };
  if (ext === '.cmd' || ext === '.bat') {
    const js = extractJsFromCmdShim(file);
    // シムを cmd.exe 経由で叩くと URL 中の & をシェルに食われる。JS を直接 node に渡す。
    return js ? { command: process.execPath, prefixArgs: [js], label } : undefined;
  }
  if (ext === '.ps1')
    return undefined;
  return { command: file, prefixArgs: [], label };
}

/**
 * playwright-cli の起動方法を解決する。
 * 解決順: PWDO_PLAYWRIGHT_CLI → PATH 上の playwright-cli → npx --no-install playwright cli
 */
export function resolvePlaywrightCli(): CliLauncher {
  const override = process.env.PWDO_PLAYWRIGHT_CLI?.trim();
  if (override) {
    const launcher = launcherForFile(override, `PWDO_PLAYWRIGHT_CLI=${override}`);
    if (!launcher)
      throw new PwdoError(`PWDO_PLAYWRIGHT_CLI の指す実体を起動できません: ${override}\n\n${PLAYWRIGHT_CLI_HINT}`);
    return launcher;
  }

  const onPath = findOnPath('playwright-cli');
  if (onPath) {
    const launcher = launcherForFile(onPath, onPath);
    if (launcher)
      return launcher;
  }

  const npx = findOnPath('npx');
  if (npx) {
    const launcher = launcherForFile(npx, `${npx} playwright cli`);
    if (launcher) {
      return {
        command: launcher.command,
        prefixArgs: [...launcher.prefixArgs, '--no-install', 'playwright', 'cli'],
        label: launcher.label,
      };
    }
  }

  throw new PwdoError(PLAYWRIGHT_CLI_HINT);
}

/**
 * pwq の起動方法を解決する。
 * 解決順: PWDO_PWQ → PATH 上の pwq → 隣のツール（`tools/browser/pwq/dist/cli.js`）。
 *
 * 隣を最後に見るのは、リポジトリ同梱の pwq をビルドしただけで pwdo が動くようにするため
 * （pwq をグローバル install させない）。**import ではなくプロセス境界**で結合する、が pwdo の決定事項。
 */
export function resolvePwq(): CliLauncher {
  const override = process.env.PWDO_PWQ?.trim();
  if (override) {
    const launcher = launcherForFile(override, `PWDO_PWQ=${override}`);
    if (!launcher)
      throw new PwdoError(`PWDO_PWQ の指す実体を起動できません: ${override}\n\n${PWQ_HINT}`);
    return launcher;
  }

  const onPath = findOnPath('pwq');
  if (onPath) {
    const launcher = launcherForFile(onPath, onPath);
    if (launcher)
      return launcher;
  }

  const sibling = path.resolve(PACKAGE_ROOT, '..', 'pwq', 'dist', 'cli.js');
  try {
    if (fs.statSync(sibling).isFile())
      return { command: process.execPath, prefixArgs: [sibling], label: sibling };
  } catch {
    // 候補はもう無い
  }

  throw new PwdoError(PWQ_HINT);
}

/**
 * pwdo が playwright-cli へ渡してよいコマンド。
 *
 * **ここに無いものは実行しない。** セッションの生成・破棄（`open` / `close` / `delete-data` …）を
 * 締め出すのが第一の目的で、委譲の途中でセッションが死ぬと呼び出し側が復帰できない。
 * `eval` / `run-code` / `state-*` / `cookie-*` を締め出すのは、何をやったのかが
 * 呼び出し側から見えなくなるため（README「配線しない操作」）。
 *
 * モデルに見せるツール（tools.ts）はこの部分集合。ここはその **下の** 防壁で、
 * ツール定義を足しただけでは新しいコマンドが通らないようにしてある。
 */
export const ALLOWED_CLI_COMMANDS = new Set([
  'snapshot', 'find',
  'goto', 'go-back', 'reload',
  'click', 'fill', 'press', 'select', 'check', 'uncheck', 'hover',
  'recording-start', 'recording-stop',
  'list',
]);

export function assertAllowedCommand(args: string[]): void {
  const command = args.find(a => !a.startsWith('-'));
  if (!command)
    throw new PwdoError('playwright-cli に渡すコマンドがありません');
  if (!ALLOWED_CLI_COMMANDS.has(command)) {
    throw new PwdoError(
      `pwdo は playwright-cli の '${command}' を実行しません（ホワイトリスト外）。\n` +
      '呼び出し側が自分で打ってください。'
    );
  }
}

export interface RunResult {
  stdout: string;
  stderr: string;
  code: number;
  /** タイムアウトで打ち切ったか */
  timedOut: boolean;
}

export interface RunOptions {
  cwd: string;
  /** 1 コマンドの上限。超えたら kill して timedOut を立てる */
  timeoutMs: number;
}

/** 子プロセスを起動し、stdout/stderr を読み切って返す。シェルは介さない。 */
export function runCli(launcher: CliLauncher, args: string[], options: RunOptions): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(launcher.command, [...launcher.prefixArgs, ...args], {
      cwd: options.cwd,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const out: Buffer[] = [];
    const err: Buffer[] = [];
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, options.timeoutMs);

    child.stdout.on('data', chunk => out.push(chunk));
    child.stderr.on('data', chunk => err.push(chunk));
    child.on('error', e => {
      clearTimeout(timer);
      reject(new PwdoError(`子プロセスの起動に失敗しました (${launcher.label}): ${e}`));
    });
    child.on('close', code => {
      clearTimeout(timer);
      resolve({
        stdout: Buffer.concat(out).toString('utf-8'),
        stderr: Buffer.concat(err).toString('utf-8'),
        code: code ?? 0,
        timedOut,
      });
    });
  });
}
