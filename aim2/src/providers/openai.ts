import type { ProviderAdapter, ProviderContext } from './types.js';
import type { LanguageModel } from 'ai';

export class OpenAIAdapter implements ProviderAdapter {
  readonly provider = 'openai';

  async createModel(modelId: string, context?: ProviderContext): Promise<LanguageModel> {
    const { createOpenAI } = await import('@ai-sdk/openai');
    const client = createOpenAI({
      apiKey: context?.apiKey,
      baseURL: context?.baseURL,
    });
    return client(modelId);
  }
}

export default new OpenAIAdapter();
