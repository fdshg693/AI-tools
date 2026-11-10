import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { simulateReadableStream } from 'ai';
import { MockLanguageModelV4 } from 'ai/test';
import { executeModel, runPrompt, RunnerError } from '../src/runner.js';
import { ProviderRegistry } from '../src/providers/registry.js';
import type { ProviderAdapter } from '../src/providers/types.js';

describe('runner (Model execution engine)', () => {
  it('executeModel with stream=false returns full text and usage', async () => {
    const model = new MockLanguageModelV4({
      provider: 'mock',
      modelId: 'mock-model',
      doGenerate: async () => ({
        content: [{ type: 'text', text: 'hello from generateText' }],
        finishReason: { unified: 'stop', raw: undefined },
        usage: {
          inputTokens: {
            total: 10,
            noCache: 10,
            cacheRead: undefined,
            cacheWrite: undefined,
          },
          outputTokens: {
            total: 5,
            text: 5,
            reasoning: undefined,
          },
        },
        warnings: [],
        rawCall: { rawPrompt: null, rawSettings: {} },
      }),
    });

    const result = await executeModel({
      model,
      prompt: 'test prompt',
      stream: false,
    });

    assert.equal(result.text, 'hello from generateText');
    assert.equal(result.finishReason, 'stop');
    assert.equal(result.usage?.promptTokens, 10);
    assert.equal(result.usage?.completionTokens, 5);
    assert.equal(model.doGenerateCalls.length, 1);
  });

  it('executeModel with stream=true calls onChunk and returns full text', async () => {
    const model = new MockLanguageModelV4({
      provider: 'mock',
      modelId: 'mock-model',
      doStream: async () => ({
        stream: simulateReadableStream({
          chunks: [
            { type: 'text-start', id: 't1' },
            { type: 'text-delta', id: 't1', delta: 'chunk1 ' },
            { type: 'text-delta', id: 't1', delta: 'chunk2' },
            { type: 'text-end', id: 't1' },
            {
              type: 'finish',
              finishReason: { unified: 'stop', raw: undefined },
              logprobs: undefined,
              usage: {
                inputTokens: {
                  total: 10,
                  noCache: 10,
                  cacheRead: undefined,
                  cacheWrite: undefined,
                },
                outputTokens: {
                  total: 5,
                  text: 5,
                  reasoning: undefined,
                },
              },
            },
          ],
        }),
        rawCall: { rawPrompt: null, rawSettings: {} },
      }),
    });

    const chunks: string[] = [];
    const result = await executeModel({
      model,
      prompt: 'test prompt',
      stream: true,
      onChunk: (chunk) => chunks.push(chunk),
    });

    assert.equal(result.text, 'chunk1 chunk2');
    assert.deepEqual(chunks, ['chunk1 ', 'chunk2']);
    assert.equal(result.finishReason, 'stop');
    assert.equal(model.doStreamCalls.length, 1);
  });

  it('executeModel accepts message history input for stream=false', async () => {
    const model = new MockLanguageModelV4({
      provider: 'mock',
      modelId: 'mock-model',
      doGenerate: async () => ({
        content: [{ type: 'text', text: 'reply from messages' }],
        finishReason: { unified: 'stop', raw: undefined },
        usage: {
          inputTokens: {
            total: 12,
            noCache: 12,
            cacheRead: undefined,
            cacheWrite: undefined,
          },
          outputTokens: {
            total: 4,
            text: 4,
            reasoning: undefined,
          },
        },
        warnings: [],
        rawCall: { rawPrompt: null, rawSettings: {} },
      }),
    });

    const result = await executeModel({
      model,
      prompt: [
        { role: 'user', content: 'first question' },
        { role: 'assistant', content: 'first answer' },
        { role: 'user', content: 'follow-up question' },
      ],
      stream: false,
    });

    assert.equal(result.text, 'reply from messages');
    assert.equal(model.doGenerateCalls.length, 1);
    assert.ok(Array.isArray((model.doGenerateCalls[0] as any).prompt));
  });

  it('executeModel accepts message history input for stream=true', async () => {
    const model = new MockLanguageModelV4({
      provider: 'mock',
      modelId: 'mock-model',
      doStream: async () => ({
        stream: simulateReadableStream({
          chunks: [
            { type: 'text-start', id: 't1' },
            { type: 'text-delta', id: 't1', delta: 'message ' },
            { type: 'text-delta', id: 't1', delta: 'reply' },
            { type: 'text-end', id: 't1' },
            {
              type: 'finish',
              finishReason: { unified: 'stop', raw: undefined },
              logprobs: undefined,
              usage: {
                inputTokens: {
                  total: 15,
                  noCache: 15,
                  cacheRead: undefined,
                  cacheWrite: undefined,
                },
                outputTokens: {
                  total: 5,
                  text: 5,
                  reasoning: undefined,
                },
              },
            },
          ],
        }),
        rawCall: { rawPrompt: null, rawSettings: {} },
      }),
    });

    const result = await executeModel({
      model,
      prompt: [
        { role: 'user', content: 'first question' },
        { role: 'assistant', content: 'first answer' },
        { role: 'user', content: 'follow-up question' },
      ],
      stream: true,
      onChunk: () => {},
    });

    assert.equal(result.text, 'message reply');
    assert.equal(model.doStreamCalls.length, 1);
    assert.ok(Array.isArray((model.doStreamCalls[0] as any).prompt));
  });

  it('executeModel wraps error into RunnerError on failure', async () => {
    const failingModel = new MockLanguageModelV4({
      provider: 'failing',
      modelId: 'fail',
      doGenerate: async () => {
        throw new Error('network timeout');
      },
    });

    await assert.rejects(
      async () => {
        await executeModel({
          model: failingModel,
          prompt: 'test prompt',
          stream: false,
        });
      },
      (err: Error) => {
        assert(err instanceof RunnerError);
        assert(err.message.includes('network timeout'));
        return true;
      }
    );
  });

  it('runPrompt resolves model from registry and executes', async () => {
    const model = new MockLanguageModelV4({
      provider: 'custom',
      modelId: 'my-model',
      doGenerate: async () => ({
        content: [{ type: 'text', text: 'hello from generateText' }],
        finishReason: { unified: 'stop', raw: undefined },
        usage: {
          inputTokens: {
            total: 10,
            noCache: 10,
            cacheRead: undefined,
            cacheWrite: undefined,
          },
          outputTokens: {
            total: 5,
            text: 5,
            reasoning: undefined,
          },
        },
        warnings: [],
        rawCall: { rawPrompt: null, rawSettings: {} },
      }),
    });

    const customRegistry = new ProviderRegistry();
    const mockAdapter: ProviderAdapter = {
      provider: 'custom',
      createModel: async () => model,
    };
    customRegistry.register('custom', async () => mockAdapter);

    const result = await runPrompt('custom', 'my-model', 'hi', {
      registry: customRegistry,
      stream: false,
      context: { apiKey: 'dummy' },
    });

    assert.equal(result.text, 'hello from generateText');
  });
});
