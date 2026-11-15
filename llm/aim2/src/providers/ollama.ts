import type { ProviderAdapter, ProviderContext } from './types.js';
import type { LanguageModel } from 'ai';

export class OllamaAdapter implements ProviderAdapter {
  readonly provider = 'ollama';

  async createModel(modelId: string, context?: ProviderContext): Promise<LanguageModel> {
    const { createOpenAI } = await import('@ai-sdk/openai');
    const client = createOpenAI({
      baseURL: context?.baseURL || 'http://127.0.0.1:11434/v1',
      apiKey: context?.apiKey || 'ollama',
    });
    return client(modelId);
  }
}

export default new OllamaAdapter();
