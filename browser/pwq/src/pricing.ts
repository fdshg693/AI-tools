/**
 * 概算コスト。OpenRouter Models API から単価を引く（aim2 の pricing.ts の最小版）。
 *
 * 値段はモデル一覧の取得に 1 リクエスト要る。既定では呼ばず、`--cost` を付けたときだけ。
 * 取得に失敗してもコマンド自体は失敗させない（コストは付随情報）。
 */

const MODELS_API = 'https://openrouter.ai/api/v1/models';
const FETCH_TIMEOUT_MS = 10_000;
const PER_MILLION = 1_000_000;

export interface ModelPrice {
  /** $ / 1M 入力トークン */
  promptPerMillion: number;
  /** $ / 1M 出力トークン */
  completionPerMillion: number;
}

export async function fetchModelPrice(modelId: string, apiKey?: string): Promise<ModelPrice | undefined> {
  const res = await fetch(MODELS_API, {
    headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : undefined,
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok)
    throw new Error(`OpenRouter Models API が ${res.status} を返しました`);
  const json = await res.json() as { data?: { id: string; pricing?: Record<string, unknown> }[] };
  const entry = json.data?.find(m => m.id === modelId);
  if (!entry?.pricing)
    return undefined;
  return {
    promptPerMillion: Number(entry.pricing.prompt ?? 0) * PER_MILLION,
    completionPerMillion: Number(entry.pricing.completion ?? 0) * PER_MILLION,
  };
}

export function estimateCostUsd(
  price: ModelPrice, usage: { inputTokens?: number; outputTokens?: number }
): number {
  return (
    ((usage.inputTokens ?? 0) * price.promptPerMillion +
     (usage.outputTokens ?? 0) * price.completionPerMillion) / PER_MILLION
  );
}

export function formatUsd(v: number): string {
  if (v === 0)
    return '$0';
  if (v < 0.01)
    return `$${v.toFixed(6)}`;
  return `$${v.toFixed(4)}`;
}
