import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

/**
 * モデル設定と API キーの解決。
 *
 * 形式は tools/llm/aim2 の `models.json`（alias → provider/id、`enable`、`default`）を踏襲する。
 * 既存ツールと同じ運用・同じ環境変数（`OPENROUTER_API_KEY`）に揃えて、覚えることを増やさない。
 */

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, '..');
export const DEFAULT_MODELS_PATH = path.join(PACKAGE_ROOT, 'models.json');
export const EXAMPLE_MODELS_PATH = path.join(PACKAGE_ROOT, 'models.json.example');

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

export const DEFAULT_ENV_PATH = path.join(PACKAGE_ROOT, '.env');

/**
 * package.json の version を読む（版数の正本。maintenance/docs/tool-conventions.md）。
 */
export function readPackageVersion(): string {
  const raw = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, 'package.json'), 'utf-8'));
  const version = String(raw.version ?? '').trim();
  if (!version)
    throw new ConfigError(`package.json の version が見つかりません: ${PACKAGE_ROOT}`);
  return version;
}

/**
 * cwd から親へ `.git`（ディレクトリ、または worktree・サブモジュールのファイル）を探す。
 * 見つからなければ undefined。`git` コマンドは呼ばない。
 */
export function findGitRoot(start: string): string | undefined {
  let dir = path.resolve(start);
  for (;;) {
    if (fs.existsSync(path.join(dir, '.git')))
      return dir;
    const parent = path.dirname(dir);
    if (parent === dir)
      return undefined;
    dir = parent;
  }
}

/** 相対パスの基準。git ルート、git 管理外なら cwd（tool-conventions 規則 4）。 */
export function baseDir(cwd: string): string {
  return findGitRoot(cwd) ?? cwd;
}

export interface DotenvResult {
  /** 想定した .env の絶対パス（固定 1 か所） */
  path: string;
  /** そのファイルを読めたか */
  loaded: boolean;
}

/**
 * ツール直下の固定パスの `.env` だけをロードする（祖先ディレクトリへは遡らない）。
 * プロセス環境変数（空文字含む）が既にあれば上書きしない。
 */
export function loadDotenv(envPath = DEFAULT_ENV_PATH): DotenvResult {
  let text: string;
  try {
    text = fs.readFileSync(envPath, 'utf-8');
  } catch {
    return { path: envPath, loaded: false };
  }
  for (const raw of text.split(/\r?\n/)) {
    let line = raw.trim();
    if (!line || line.startsWith('#'))
      continue;
    if (line.startsWith('export '))
      line = line.slice(7).trim();
    const eq = line.indexOf('=');
    if (eq === -1)
      continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (value.length >= 2 && value[0] === value[value.length - 1] && (value[0] === '"' || value[0] === "'"))
      value = value.slice(1, -1);
    if (key && !(key in process.env))
      process.env[key] = value;
  }
  return { path: envPath, loaded: true };
}

export interface ProviderAuth {
  apiKey?: string;
  baseURL?: string;
}

/**
 * 鍵が無いことは fatal にしない（LLM は付加価値であって前提ではない）。
 * 呼び出し側が undefined を見て決定論的ダイジェストだけに落とす。
 */
export function resolveApiKey(provider: string): ProviderAuth | undefined {
  if (provider !== 'openrouter')
    return undefined;
  const key = process.env.OPENROUTER_API_KEY?.trim();
  if (!key)
    return undefined;
  return { apiKey: key, baseURL: process.env.OPENROUTER_BASE_URL?.trim() || undefined };
}

/**
 * 必須キー欠落の診断（tool-conventions「必須キーが無いときのエラー」）。
 * 環境変数の状態と、想定した .env の絶対パス・状態を必ず出す。
 */
export function missingKeyMessage(provider: string, env: DotenvResult): string {
  const envVar = provider === 'openrouter' ? 'OPENROUTER_API_KEY' : `${provider.toUpperCase()}_API_KEY`;
  const envState = envVar in process.env ? '空で設定されている' : '未設定';
  const fileState = env.loaded
    ? `${env.path} はありますが、${envVar} が無いか空です。`
    : `想定した .env は ${env.path} ですが、ファイルがありません。`;
  return `${envVar} が解決できません。
環境変数 ${envVar} は${envState}です。
${fileState}`;
}

export interface ModelSpec {
  enable: boolean;
  provider: string;
  id: string;
  description: string;
}

export interface ModelsConfig {
  default: string;
  models: Record<string, ModelSpec>;
  /** 読み込み元。models.json が無く .example にフォールバックしたときの表示用 */
  sourcePath: string;
}

export function validateModelsConfig(raw: unknown, sourcePath: string): ModelsConfig {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw))
    throw new ConfigError(`${sourcePath} は空でないオブジェクトである必要があります`);
  const record = raw as Record<string, unknown>;

  const defaultAlias = record.default;
  if (typeof defaultAlias !== 'string' || !defaultAlias.trim())
    throw new ConfigError(`${sourcePath} の default が不正です: ${JSON.stringify(defaultAlias)}`);

  const modelsRaw = record.models;
  if (!modelsRaw || typeof modelsRaw !== 'object' || Array.isArray(modelsRaw))
    throw new ConfigError(`${sourcePath} の models は空でないオブジェクト（略記 → 定義）である必要があります`);

  const models: Record<string, ModelSpec> = {};
  for (const [alias, specRaw] of Object.entries(modelsRaw as Record<string, unknown>)) {
    if (!alias.trim())
      throw new ConfigError(`${sourcePath} の略記が空です`);
    if (!specRaw || typeof specRaw !== 'object' || Array.isArray(specRaw))
      throw new ConfigError(`${sourcePath} のモデル定義が不正です（略記 '${alias}'）`);
    const spec = specRaw as Record<string, unknown>;
    for (const field of ['provider', 'id', 'description'] as const) {
      if (typeof spec[field] !== 'string' || !(spec[field] as string).trim())
        throw new ConfigError(`${sourcePath} の ${field} が空でない文字列ではありません（略記 '${alias}'）`);
    }
    if (typeof spec.enable !== 'boolean')
      throw new ConfigError(`${sourcePath} の enable が真偽値ではありません（略記 '${alias}'）`);
    models[alias] = {
      enable: spec.enable,
      provider: (spec.provider as string).trim().toLowerCase(),
      id: (spec.id as string).trim(),
      description: (spec.description as string).trim(),
    };
  }

  if (!Object.keys(models).length)
    throw new ConfigError(`${sourcePath} の models にモデル定義が 1 つも含まれていません`);
  if (!(defaultAlias in models))
    throw new ConfigError(`${sourcePath} の default '${defaultAlias}' は models の略記に含まれていません`);
  if (!models[defaultAlias].enable)
    throw new ConfigError(`${sourcePath} の default '${defaultAlias}' は enable: false です`);

  return { default: defaultAlias, models, sourcePath };
}

/**
 * `models.json` を読む。無ければ `models.json.example` にフォールバックする
 * （models.json は gitignore 済みなので、clone 直後でも動くようにするため）。
 */
export function loadModels(modelsPath = DEFAULT_MODELS_PATH): ModelsConfig {
  const candidates = [modelsPath, EXAMPLE_MODELS_PATH];
  for (const p of candidates) {
    let text: string;
    try {
      text = fs.readFileSync(p, 'utf-8');
    } catch {
      continue;
    }
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch (err) {
      throw new ConfigError(`${p} の JSON が不正です: ${err}`);
    }
    return validateModelsConfig(raw, p);
  }
  throw new ConfigError(`モデル定義ファイルが見つかりません: ${candidates.join(' / ')}`);
}

export interface ResolvedModel {
  alias: string;
  spec: ModelSpec;
}

export function resolveModel(config: ModelsConfig, input?: string): ResolvedModel {
  const alias = input?.trim() || config.default;
  const spec = config.models[alias];
  if (!spec) {
    const available = Object.entries(config.models)
      .filter(([, s]) => s.enable).map(([a]) => a).join(', ');
    throw new ConfigError(`未知のモデル略記です: '${alias}'\n利用可能な略記: ${available}`);
  }
  if (!spec.enable)
    throw new ConfigError(`モデル略記 '${alias}' (${spec.id}) は enable: false です`);
  return { alias, spec };
}
