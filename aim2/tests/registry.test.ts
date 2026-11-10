import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { ProviderRegistry, defaultRegistry } from '../src/providers/registry.js';
import type { ProviderAdapter, ProviderContext } from '../src/providers/types.js';
import type { LanguageModel } from 'ai';
import { ConfigError } from '../src/config.js';

describe('ProviderRegistry', () => {
  it('デフォルトのプロバイダが全て登録されている', () => {
    const registry = new ProviderRegistry();
    const providers = registry.getSupportedProviders();

    assert(providers.includes('openai'));
    assert(providers.includes('anthropic'));
    assert(providers.includes('google'));
    assert(providers.includes('openrouter'));
    assert(providers.includes('ollama'));
  });

  it('未対応のプロバイダを指定した場合は ConfigError をスローする', async () => {
    const registry = new ProviderRegistry();
    await assert.rejects(
      async () => {
        await registry.getAdapter('unknown-provider');
      },
      (err: unknown) => {
        assert(err instanceof ConfigError);
        assert.match(err.message, /未対応のプロバイダです: 'unknown-provider'/);
        assert.match(err.message, /対応プロバイダ一覧:/);
        return true;
      }
    );
  });

  it('カスタムプロバイダを登録・取得できる', async () => {
    const registry = new ProviderRegistry();

    const mockAdapter: ProviderAdapter = {
      provider: 'custom',
      async createModel(modelId: string, context?: ProviderContext): Promise<LanguageModel> {
        return {
          modelId,
          provider: 'custom',
        } as unknown as LanguageModel;
      },
    };

    registry.register('custom', async () => mockAdapter);

    assert(registry.has('custom'));
    const adapter = await registry.getAdapter('custom');
    assert.equal(adapter.provider, 'custom');

    const model = await registry.resolveLanguageModel('custom', 'my-model', { apiKey: 'test' });
    assert.equal((model as { modelId?: string }).modelId, 'my-model');
  });

  it('各標準プロバイダのアダプタから LanguageModel インスタンスを生成できる', async () => {
    // defaultRegistry を使用
    const getModelId = (model: LanguageModel): string => {
      return (model as { modelId?: string }).modelId || '';
    };

    const openaiModel = await defaultRegistry.resolveLanguageModel('openai', 'gpt-4o', {
      apiKey: 'sk-dummy-test-key',
    });
    assert.equal(getModelId(openaiModel), 'gpt-4o');

    const anthropicModel = await defaultRegistry.resolveLanguageModel(
      'anthropic',
      'claude-3-7-sonnet',
      { apiKey: 'sk-ant-dummy' }
    );
    assert.equal(getModelId(anthropicModel), 'claude-3-7-sonnet');

    const googleModel = await defaultRegistry.resolveLanguageModel('google', 'gemini-2.5-flash', {
      apiKey: 'dummy-google-key',
    });
    assert.equal(getModelId(googleModel), 'gemini-2.5-flash');

    const openrouterModel = await defaultRegistry.resolveLanguageModel(
      'openrouter',
      'z-ai/glm-5.3-flash',
      { apiKey: 'sk-or-dummy' }
    );
    assert.equal(getModelId(openrouterModel), 'z-ai/glm-5.3-flash');

    const ollamaModel = await defaultRegistry.resolveLanguageModel('ollama', 'llama3.2', {
      baseURL: 'http://localhost:11434/v1',
    });
    assert.equal(getModelId(ollamaModel), 'llama3.2');
  });
});
