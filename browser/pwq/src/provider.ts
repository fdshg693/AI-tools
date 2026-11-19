import type { LanguageModel } from 'ai';
import type { ProviderAuth } from './config.js';

/**
 * モデルの実体化。
 *
 * aim2 の registry は複数プロバイダを束ねるためのものだが、`pwq` は OpenRouter 1 本に絞る
 * （OpenRouter 自体が各社モデルへのルータなので、二重の抽象は要らない）。
 * import は動的にして、LLM を呼ばない経路（Step2 のダイジェストのみ）で SDK をロードしない。
 */
export async function createModel(
  provider: string, modelId: string, auth: ProviderAuth
): Promise<LanguageModel> {
  if (provider !== 'openrouter') {
    throw new Error(
      `pwq が対応しているプロバイダは openrouter だけです（指定: '${provider}'）。\n` +
      `models.json の provider を openrouter にするか、OpenRouter 上の同等モデル id を指定してください。`
    );
  }
  const { createOpenRouter } = await import('@openrouter/ai-sdk-provider');
  const client = createOpenRouter({ apiKey: auth.apiKey, baseURL: auth.baseURL });
  return client(modelId);
}
