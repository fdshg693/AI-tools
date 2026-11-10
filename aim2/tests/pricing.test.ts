import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  perMillionTokens,
  estimatePromptTokens,
  worstCasePricePerToken,
  splitOpenRouterModelId,
  formatPerMillion,
  formatCostText,
  formatCostJson,
  getModelCost,
  PricingError,
} from '../src/pricing.js';

describe('pricing', () => {
  it('perMillionTokens multiplies by 1,000,000', () => {
    assert.equal(perMillionTokens(0.000001), 1);
    assert.equal(perMillionTokens(0.0000025), 2.5);
  });

  it('estimatePromptTokens estimates tokens using ceil(chars / 4)', () => {
    assert.equal(estimatePromptTokens(''), 0);
    assert.equal(estimatePromptTokens('abcd'), 1);
    assert.equal(estimatePromptTokens('abcde'), 2);
  });

  it('worstCasePricePerToken picks maximum value from base and overrides', () => {
    const pricing = {
      prompt: '0.000001',
      completion: '0.000002',
      overrides: [
        { prompt: '0.000003' },
        { completion: '0.0000015' },
      ],
    };
    assert.equal(worstCasePricePerToken(pricing, 'prompt'), 0.000003);
    assert.equal(worstCasePricePerToken(pricing, 'completion'), 0.000002);
  });

  it('splitOpenRouterModelId splits author/slug correctly', () => {
    const res = splitOpenRouterModelId('openai/gpt-4o');
    assert.deepEqual(res, { author: 'openai', slug: 'gpt-4o' });

    assert.throws(() => splitOpenRouterModelId('invalid-no-slash'), PricingError);
  });

  it('formatPerMillion strips trailing zeros', () => {
    assert.equal(formatPerMillion(0), '0');
    assert.equal(formatPerMillion(1.5), '1.5');
    assert.equal(formatPerMillion(0.25000000), '0.25');
  });

  it('formatCostText and formatCostJson formats correctly', () => {
    const cost = {
      modelId: 'z-ai/glm-5.3-flash',
      provider: 'openrouter',
      promptPerMillion: 0.1,
      completionPerMillion: 0.2,
    };
    const text = formatCostText('glm-5.3-flash', cost);
    assert.match(text, /glm-5\.3-flash/);
    assert.match(text, /0\.1 \$\/M tokens/);

    const json = JSON.parse(formatCostJson('glm-5.3-flash', cost));
    assert.equal(json.alias, 'glm-5.3-flash');
    assert.equal(json.prompt_per_million, 0.1);
  });

  it('getModelCost returns 0 for ollama', async () => {
    const cost = await getModelCost('ollama', 'llama3.2');
    assert.equal(cost.promptPerMillion, 0);
    assert.equal(cost.completionPerMillion, 0);
  });

  it('getModelCost throws for unsupported direct provider', async () => {
    await assert.rejects(
      async () => {
        await getModelCost('openai', 'gpt-4o');
      },
      PricingError
    );
  });
});
