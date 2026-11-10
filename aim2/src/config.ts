import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = path.resolve(SCRIPT_DIR, '..');
export const DEFAULT_ENV_PATH = path.join(PACKAGE_ROOT, '.env');
export const DEFAULT_MODELS_PATH = path.join(PACKAGE_ROOT, 'models.json');


export function readPackageVersion(): string {
  const raw = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, 'package.json'), 'utf-8'));
  const version = String(raw.version ?? '').trim();
  if (!version) {
    throw new ConfigError(`package.json の version が見つかりません: ${PACKAGE_ROOT}`);
  }
  return version;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

/**
 * リポジトリ規約 (docs/repo-wide/tool-conventions.md) に準拠した必須キー欠落診断メッセージ。
 */
export function missingRequiredKeyMessage(key: string, envPath = DEFAULT_ENV_PATH): string {
  const envState = key in process.env ? '空で設定されている' : '未設定';
  let fileState: string;
  try {
    const stat = fs.statSync(envPath);
    if (stat.isFile()) {
      fileState = `${envPath} はありますが、${key} が無いか空です。`;
    } else {
      fileState = `想定した .env は ${envPath} ですが、ファイルがありません。`;
    }
  } catch {
    fileState = `想定した .env は ${envPath} ですが、ファイルがありません。`;
  }
  return `${key} が解決できません。\n環境変数 ${key} は${envState}です。\n${fileState}`;
}

/**
 * 固定パスの .env をロードする。
 * プロセス環境変数（空文字含む）が存在する場合は上書きしない。
 */
export function loadDotenv(envPath = DEFAULT_ENV_PATH): void {
  let text: string;
  try {
    text = fs.readFileSync(envPath, 'utf-8');
  } catch {
    return;
  }

  for (const raw of text.split(/\r?\n/)) {
    let line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('export ')) {
      line = line.slice(7).trim();
    }
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      value.length >= 2 &&
      value[0] === value[value.length - 1] &&
      (value[0] === '"' || value[0] === "'")
    ) {
      value = value.slice(1, -1);
    }
    if (key && !(key in process.env)) {
      process.env[key] = value;
    }
  }
}

export interface ProviderAuth {
  apiKey?: string;
  baseURL?: string;
}

/**
 * 指定されたプロバイダに必要な認証情報を解決・検証する。
 * 利用しないプロバイダのキー欠落は無視する。
 */
export function resolveApiKey(provider: string, envPath = DEFAULT_ENV_PATH): ProviderAuth {
  const normalizedProvider = provider.toLowerCase();

  switch (normalizedProvider) {
    case 'openai': {
      const key = process.env.OPENAI_API_KEY;
      if (!key || !key.trim()) {
        throw new ConfigError(missingRequiredKeyMessage('OPENAI_API_KEY', envPath));
      }
      return { apiKey: key.trim(), baseURL: process.env.OPENAI_BASE_URL?.trim() };
    }
    case 'anthropic': {
      const key = process.env.ANTHROPIC_API_KEY;
      if (!key || !key.trim()) {
        throw new ConfigError(missingRequiredKeyMessage('ANTHROPIC_API_KEY', envPath));
      }
      return { apiKey: key.trim(), baseURL: process.env.ANTHROPIC_BASE_URL?.trim() };
    }
    case 'google': {
      const key = process.env.GEMINI_API_KEY || process.env.GOOGLE_GENERATIVE_AI_API_KEY;
      if (!key || !key.trim()) {
        throw new ConfigError(missingRequiredKeyMessage('GEMINI_API_KEY', envPath));
      }
      return { apiKey: key.trim(), baseURL: process.env.GOOGLE_BASE_URL?.trim() };
    }
    case 'openrouter': {
      const key = process.env.OPENROUTER_API_KEY;
      if (!key || !key.trim()) {
        throw new ConfigError(missingRequiredKeyMessage('OPENROUTER_API_KEY', envPath));
      }
      return { apiKey: key.trim(), baseURL: process.env.OPENROUTER_BASE_URL?.trim() };
    }
    case 'ollama': {
      const baseURL = process.env.OLLAMA_BASE_URL?.trim() || 'http://127.0.0.1:11434/v1';
      return { baseURL };
    }
    default: {
      // 未知のプロバイダの場合は汎用環境変数を参照
      const envKey = `${normalizedProvider.toUpperCase()}_API_KEY`;
      const key = process.env[envKey];
      return { apiKey: key?.trim() };
    }
  }
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
}

/**
 * モデル設定オブジェクトを厳密に検証する。
 */
export function validateModelsConfig(raw: unknown, sourcePath = DEFAULT_MODELS_PATH): ModelsConfig {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new ConfigError(`${sourcePath} は空でないオブジェクトである必要があります`);
  }

  const record = raw as Record<string, unknown>;

  const defaultAlias = record.default;
  if (typeof defaultAlias !== 'string' || !defaultAlias.trim()) {
    throw new ConfigError(`${sourcePath} の default が不正です: ${JSON.stringify(defaultAlias)}`);
  }

  const modelsRaw = record.models;
  if (!modelsRaw || typeof modelsRaw !== 'object' || Array.isArray(modelsRaw)) {
    throw new ConfigError(
      `${sourcePath} の models は空でないオブジェクト（略記 → 定義）である必要があります`
    );
  }

  const modelsRecord = modelsRaw as Record<string, unknown>;
  const keys = Object.keys(modelsRecord);
  if (keys.length === 0) {
    throw new ConfigError(`${sourcePath} の models にモデル定義が 1 つも含まれていません`);
  }

  const models: Record<string, ModelSpec> = {};

  for (const [alias, specRaw] of Object.entries(modelsRecord)) {
    if (!alias.trim()) {
      throw new ConfigError(`${sourcePath} の略記が空です`);
    }
    if (!specRaw || typeof specRaw !== 'object' || Array.isArray(specRaw)) {
      throw new ConfigError(
        `${sourcePath} のモデル定義が不正です（略記 '${alias}'）: ${JSON.stringify(specRaw)}`
      );
    }

    const spec = specRaw as Record<string, unknown>;

    if (typeof spec.enable !== 'boolean') {
      throw new ConfigError(
        `${sourcePath} の enable が真偽値ではありません（略記 '${alias}'）: ${JSON.stringify(spec.enable)}`
      );
    }

    if (typeof spec.provider !== 'string' || !spec.provider.trim()) {
      throw new ConfigError(
        `${sourcePath} の provider が空でない文字列ではありません（略記 '${alias}'）: ${JSON.stringify(spec.provider)}`
      );
    }

    if (typeof spec.id !== 'string' || !spec.id.trim()) {
      throw new ConfigError(
        `${sourcePath} のモデルID（id）が空でない文字列ではありません（略記 '${alias}'）: ${JSON.stringify(spec.id)}`
      );
    }

    if (typeof spec.description !== 'string' || !spec.description.trim()) {
      throw new ConfigError(
        `${sourcePath} の description が空でない文字列ではありません（略記 '${alias}'）: ${JSON.stringify(spec.description)}`
      );
    }

    models[alias] = {
      enable: spec.enable,
      provider: spec.provider.trim().toLowerCase(),
      id: spec.id.trim(),
      description: spec.description.trim(),
    };
  }

  if (!(defaultAlias in models)) {
    throw new ConfigError(
      `${sourcePath} の default '${defaultAlias}' は models の略記に含まれていません`
    );
  }

  if (!models[defaultAlias].enable) {
    throw new ConfigError(
      `${sourcePath} の default '${defaultAlias}' は enable: false に設定されています`
    );
  }

  return {
    default: defaultAlias,
    models,
  };
}

/**
 * models.json を読み込みバリデーションを行う。
 */
export function loadModels(modelsPath = DEFAULT_MODELS_PATH): ModelsConfig {
  if (!fs.existsSync(modelsPath)) {
    throw new ConfigError(`モデル定義ファイルが見つかりません: ${modelsPath}`);
  }

  let rawText: string;
  try {
    rawText = fs.readFileSync(modelsPath, 'utf-8');
  } catch (err) {
    throw new ConfigError(`モデル定義ファイルの読み込みに失敗しました: ${modelsPath} (${err})`);
  }

  let raw: unknown;
  try {
    raw = JSON.parse(rawText);
  } catch (err) {
    throw new ConfigError(`${modelsPath} の JSON が不正です: ${err}`);
  }

  return validateModelsConfig(raw, modelsPath);
}

export interface ResolvedModel {
  alias: string;
  spec: ModelSpec;
}

/**
 * 指定されたモデル入力（略記）を解決する。
 * 省略時はデフォルトモデルを解決する。
 */
export function resolveModel(modelsConfig: ModelsConfig, modelInput?: string): ResolvedModel {
  const targetAlias = modelInput?.trim() || modelsConfig.default;

  const spec = modelsConfig.models[targetAlias];
  if (!spec) {
    const available = Object.keys(modelsConfig.models).join(', ');
    throw new ConfigError(
      `未知のモデル略記です: '${targetAlias}'\n利用可能な略記: ${available}`
    );
  }

  if (!spec.enable) {
    throw new ConfigError(
      `モデル略記 '${targetAlias}' (${spec.id}) は無効化 (enable: false) されています`
    );
  }

  return {
    alias: targetAlias,
    spec,
  };
}
