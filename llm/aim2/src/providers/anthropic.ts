import type { ProviderAdapter, ProviderContext } from './types.js';
import type { LanguageModel } from 'ai';

export class AnthropicAdapter implements ProviderAdapter {
  readonly provider = 'anthropic';

  async createModel(modelId: string, context?: ProviderContext): Promise<LanguageModel> {
    const { createAnthropic } = await import('@ai-sdk/anthropic');
    const client = createAnthropic({
      apiKey: context?.apiKey,
      baseURL: context?.baseURL,
    });
    return client(modelId);
  }
}

export default new AnthropicAdapter();
