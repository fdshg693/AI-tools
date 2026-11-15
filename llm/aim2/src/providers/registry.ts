import type { LanguageModel } from 'ai';
import type { ProviderAdapter, ProviderContext, ProviderLoader } from './types.js';
import { resolveApiKey, ConfigError } from '../config.js';
import { OpenAIAdapter } from './openai.js';
import { AnthropicAdapter } from './anthropic.js';
import { GoogleAdapter } from './google.js';
import { OpenRouterAdapter } from './openrouter.js';
import { OllamaAdapter } from './ollama.js';

export class ProviderRegistry {
  private loaders = new Map<string, ProviderLoader>();
  private adapters = new Map<string, ProviderAdapter>();

  constructor() {
    this.registerDefaultProviders();
  }

  private registerDefaultProviders(): void {
    this.register('openai', async () => new OpenAIAdapter());
    this.register('anthropic', async () => new AnthropicAdapter());
    this.register('google', async () => new GoogleAdapter());
    this.register('openrouter', async () => new OpenRouterAdapter());
    this.register('ollama', async () => new OllamaAdapter());
  }

  register(providerName: string, loader: ProviderLoader): void {
    this.loaders.set(providerName.toLowerCase(), loader);
  }

  has(providerName: string): boolean {
    return this.loaders.has(providerName.toLowerCase());
  }

  getSupportedProviders(): string[] {
    return Array.from(this.loaders.keys());
  }

  async getAdapter(providerName: string): Promise<ProviderAdapter> {
    const key = providerName.toLowerCase();
    if (this.adapters.has(key)) {
      return this.adapters.get(key)!;
    }

    const loader = this.loaders.get(key);
    if (!loader) {
      const supported = this.getSupportedProviders().join(', ');
      throw new ConfigError(
        `未対応のプロバイダです: '${providerName}'\n対応プロバイダ一覧: ${supported}`
      );
    }

    const adapter = await loader();
    this.adapters.set(key, adapter);
    return adapter;
  }

  /**
   * プロバイダ名、モデルID、および認証コンテキストから LanguageModel を生成・解決する。
   * context が省略されているかキー未指定の場合は、環境変数およびツール直下 .env から解決する。
   */
  async resolveLanguageModel(
    providerName: string,
    modelId: string,
    context?: ProviderContext
  ): Promise<LanguageModel> {
    const adapter = await this.getAdapter(providerName);

    let authContext = context;
    if (!authContext || (!authContext.apiKey && !authContext.baseURL)) {
      const resolved = resolveApiKey(providerName, context?.envPath);
      authContext = {
        apiKey: resolved.apiKey,
        baseURL: resolved.baseURL,
        envPath: context?.envPath,
      };
    }

    return adapter.createModel(modelId, authContext);
  }
}

export const defaultRegistry = new ProviderRegistry();
