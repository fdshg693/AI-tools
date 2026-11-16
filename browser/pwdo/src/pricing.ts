/**
 * 概算コスト。OpenRouter Models API から単価を引く（`pwq/src/pricing.ts` と同形）。
 *
 * pwdo は委譲 1 回につき開始前に 1 度だけ引く。単価が要るのはコスト上限（`--max-usd`）の
 * 判定と返却物の `cost.usd` の両方だが、取得に失敗しても委譲は落とさない
 * （`usd: null` にして続行。上限判定はステップ数と時間だけが効く）。
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
