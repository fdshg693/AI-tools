/**
 * モデル単価取得・概算計算モジュール
 * OpenRouter プロバイダに対しては OpenRouter Models API から動的取得、
 * ローカルプロバイダ（Ollama 等）は無料、その他の直接接続プロバイダには静的単価または案内を提供。
 */

export const TOKENS_PER_MILLION = 1_000_000;
export const CHARS_PER_TOKEN = 4;
export const MODEL_URL_TEMPLATE = 'https://openrouter.ai/api/v1/model/{author}/{slug}';
export const FETCH_TIMEOUT_MS = 10_000;

export class PricingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PricingError';
  }
}

export interface ModelCost {
  modelId: string;
  provider: string;
  promptPerMillion: number;
  completionPerMillion: number;
}

/**
 * $/token を $/M tokens に変換
 */
export function perMillionTokens(pricePerToken: number): number {
  return pricePerToken * TOKENS_PER_MILLION;
}

/**
 * 簡易トークン概算（切り上げ）
 */
export function estimatePromptTokens(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.length / CHARS_PER_TOKEN);
}

/**
 * 最悪ケース価格（ベース値と overrides[] の最大値）を抽出
 */
export function worstCasePricePerToken(pricing: Record<string, any>, field: 'prompt' | 'completion'): number {
  const base = Number(pricing[field] ?? 0);
  let max = Number.isNaN(base) ? 0 : base;

  if (Array.isArray(pricing.overrides)) {
    for (const item of pricing.overrides) {
      if (item && field in item) {
        const val = Number(item[field]);
        if (!Number.isNaN(val) && val > max) {
          max = val;
        }
      }
    }
  }
  return max;
}

/**
 * OpenRouter author/slug 分割
 */
export function splitOpenRouterModelId(modelId: string): { author: string; slug: string } {
  const trimmed = modelId.trim();
  const slashIdx = trimmed.indexOf('/');
  if (slashIdx === -1) {
    throw new PricingError(`OpenRouter モデルIDの形式が不正です（author/slug が必要です）: ${trimmed}`);
  }
  const author = trimmed.slice(0, slashIdx).trim();
  const slug = trimmed.slice(slashIdx + 1).trim();
  if (!author || !slug) {
    throw new PricingError(`OpenRouter モデルIDの形式が不正です: ${trimmed}`);
  }
  return { author, slug };
}

/**
 * OpenRouter Models API から単価を取得
 */
export async function fetchOpenRouterModelCost(modelId: string, timeoutMs = FETCH_TIMEOUT_MS): Promise<ModelCost> {
  const trimmed = modelId.trim();
  if (trimmed.endsWith(':free')) {
    return {
      modelId: trimmed,
      provider: 'openrouter',
      promptPerMillion: 0,
      completionPerMillion: 0,
    };
  }

  const { author, slug } = splitOpenRouterModelId(trimmed);
  const url = `https://openrouter.ai/api/v1/model/${encodeURIComponent(author)}/${slug}`;

  let res: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    res = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
  } catch (err: any) {
    clearTimeout(timer);
    if (err.name === 'AbortError') {
      throw new PricingError('OpenRouter Models API の取得がタイムアウトしました');
    }
    throw new PricingError(`OpenRouter Models API の取得に失敗しました: ${err.message || err}`);
  } finally {
    clearTimeout(timer);
  }

  if (res.status === 404 && slug.includes(':')) {
    // variant を除いたベースIDで再試行
    const baseSlug = slug.slice(0, slug.lastIndexOf(':'));
    return fetchOpenRouterModelCost(`${author}/${baseSlug}`, timeoutMs);
  }

  if (!res.ok) {
    throw new PricingError(`OpenRouter Models API HTTP ${res.status}: ${res.statusText}`);
  }

  const payload: any = await res.json();
  if (!payload || !payload.data || !payload.data.pricing) {
    throw new PricingError(`OpenRouter Models API の応答形式が不正です: ${modelId}`);
  }

  const pricing = payload.data.pricing;
  const promptPrice = worstCasePricePerToken(pricing, 'prompt');
  const completionPrice = worstCasePricePerToken(pricing, 'completion');

  return {
    modelId: trimmed,
    provider: 'openrouter',
    promptPerMillion: perMillionTokens(promptPrice),
    completionPerMillion: perMillionTokens(completionPrice),
  };
}

/**
 * プロバイダごとの単価を解決
 */
export async function getModelCost(provider: string, modelId: string): Promise<ModelCost> {
  const normProvider = provider.toLowerCase();

  if (normProvider === 'ollama') {
    return {
      modelId,
      provider: 'ollama',
      promptPerMillion: 0,
      completionPerMillion: 0,
    };
  }

  if (normProvider === 'openrouter') {
    return fetchOpenRouterModelCost(modelId);
  }

  // 現時点では OpenRouter と Ollama 以外の直接プロバイダは動的価格 API が標準提供されていないためエラー通知
  throw new PricingError(
    `プロバイダ '${provider}' の動的単価取得は現在サポートされていません（OpenRouter, Ollama のみ対応）`
  );
}

/**
 * 表示用フォーマッター
 */
export function formatPerMillion(value: number): string {
  if (value === 0) return '0';
  return value.toFixed(8).replace(/\.?0+$/, '');
}

export function formatCostText(alias: string, cost: ModelCost): string {
  const width = Math.max('prompt'.length, 'completion'.length);
  return [
    `${alias}  [${cost.provider}] ${cost.modelId}`,
    `${'prompt'.padEnd(width)}  ${formatPerMillion(cost.promptPerMillion)} $/M tokens`,
    `${'completion'.padEnd(width)}  ${formatPerMillion(cost.completionPerMillion)} $/M tokens`,
  ].join('\n');
}

export function formatCostJson(alias: string, cost: ModelCost): string {
  return JSON.stringify(
    {
      alias,
      provider: cost.provider,
      id: cost.modelId,
      prompt_per_million: cost.promptPerMillion,
      completion_per_million: cost.completionPerMillion,
      unit: '$/M tokens',
    },
    null,
    2
  );
}
