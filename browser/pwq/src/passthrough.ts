import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

export class PwqError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PwqError';
  }
}

/** playwright-cli をどう起動するか。args は常に配列で渡し、シェルは介さない。 */
export interface CliLauncher {
  /** 実行ファイル（node 自身 or シェル不要の実行可能ファイル） */
  command: string;
  /** 引数の前置き（node で .js を起動する場合の js パス等） */
  prefixArgs: string[];
  /** 人間向けの説明（エラーメッセージ用） */
  label: string;
}

const INSTALL_HINT = [
  'playwright-cli が見つかりません。',
  '',
  '  npm install -g @playwright/cli     # または pnpm add -g @playwright/cli',
  '  npx playwright cli --version       # 一時利用',
  '',
  'すでに入っている場合は PWQ_PLAYWRIGHT_CLI に実体（playwright-cli.js のパス、',
  'もしくはシェル不要な実行ファイルのパス）を指定してください。',
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
 * シムは `"%~dp0\..\path\to\cli.js"` の形でパスを埋め込んでいる。
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
 * 解決順: PWQ_PLAYWRIGHT_CLI → PATH 上の playwright-cli → npx --no-install playwright cli
 */
export function resolveLauncher(): CliLauncher {
  const override = process.env.PWQ_PLAYWRIGHT_CLI?.trim();
  if (override) {
    const launcher = launcherForFile(override, `PWQ_PLAYWRIGHT_CLI=${override}`);
    if (!launcher)
      throw new PwqError(`PWQ_PLAYWRIGHT_CLI の指す実体を起動できません: ${override}\n\n${INSTALL_HINT}`);
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

  throw new PwqError(INSTALL_HINT);
}

export interface RunResult {
  stdout: string;
  stderr: string;
  code: number;
}

/** playwright-cli を子プロセスで起動し、stdout/stderr を読み切って返す。 */
export function runCli(launcher: CliLauncher, args: string[], cwd: string): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(launcher.command, [...launcher.prefixArgs, ...args], {
      cwd,
      shell: false,
      windowsHide: true,
      stdio: ['inherit', 'pipe', 'pipe'],
    });
    const out: Buffer[] = [];
    const err: Buffer[] = [];
    child.stdout.on('data', chunk => out.push(chunk));
    child.stderr.on('data', chunk => err.push(chunk));
    child.on('error', e => reject(new PwqError(`playwright-cli の起動に失敗しました (${launcher.label}): ${e}`)));
    child.on('close', code => {
      resolve({
        stdout: Buffer.concat(out).toString('utf-8'),
        stderr: Buffer.concat(err).toString('utf-8'),
        code: code ?? 0,
      });
    });
  });
}

/** 加工せず stdout/stderr を素通しし、終了コードだけ返す。 */
export function runCliInherit(launcher: CliLauncher, args: string[], cwd: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = spawn(launcher.command, [...launcher.prefixArgs, ...args], {
      cwd,
      shell: false,
      windowsHide: true,
      stdio: 'inherit',
    });
    child.on('error', e => reject(new PwqError(`playwright-cli の起動に失敗しました (${launcher.label}): ${e}`)));
    child.on('close', code => resolve(code ?? 0));
  });
}
