import type { ProviderAdapter, ProviderContext } from './types.js';
import type { LanguageModel } from 'ai';

export class GoogleAdapter implements ProviderAdapter {
  readonly provider = 'google';

  async createModel(modelId: string, context?: ProviderContext): Promise<LanguageModel> {
    const { createGoogle } = await import('@ai-sdk/google');
    const client = createGoogle({
      apiKey: context?.apiKey,
      baseURL: context?.baseURL,
    });
    return client(modelId);
  }
}

export default new GoogleAdapter();
