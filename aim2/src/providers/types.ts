import type { LanguageModel } from 'ai';

export interface ProviderContext {
  apiKey?: string;
  baseURL?: string;
  envPath?: string;
}

export interface ProviderAdapter {
  readonly provider: string;
  createModel(modelId: string, context?: ProviderContext): Promise<LanguageModel>;
}

export type ProviderLoader = () => Promise<ProviderAdapter>;
