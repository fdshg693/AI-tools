import type { ProviderAdapter, ProviderContext } from './types.js';
import type { LanguageModel } from 'ai';

export class OpenRouterAdapter implements ProviderAdapter {
  readonly provider = 'openrouter';

  async createModel(modelId: string, context?: ProviderContext): Promise<LanguageModel> {
    const { createOpenRouter } = await import('@openrouter/ai-sdk-provider');
    const client = createOpenRouter({
      apiKey: context?.apiKey,
      baseURL: context?.baseURL,
    });
    return client(modelId);
  }
}

export default new OpenRouterAdapter();
