import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { AimError, normalizeError } from '../src/errors.js';

describe('errors: normalizeError', () => {
  it('AimError のインスタンスはそのまま返す（provider の補完あり）', () => {
    const err = new AimError('既に AimError', { code: 'CONFIG_ERROR' });
    const normalized = normalizeError(err, 'openai');
    assert.equal(normalized.code, 'CONFIG_ERROR');
    assert.equal(normalized.provider, 'openai');
    assert.equal(normalized.message, '既に AimError');
  });

  it('401 ステータスコードを AUTHENTICATION_ERROR に分類する', () => {
    const raw = Object.assign(new Error('Incorrect API key provided'), { statusCode: 401 });
    const normalized = normalizeError(raw, 'openai');
    assert.equal(normalized.code, 'AUTHENTICATION_ERROR');
    assert.equal(normalized.statusCode, 401);
    assert.equal(normalized.provider, 'openai');
    assert.match(normalized.message, /認証エラー/);
  });

  it('429 ステータスコードまたは rate limit メッセージを RATE_LIMIT_ERROR に分類する', () => {
    const raw = new Error('You exceeded your current quota, please check your plan');
    const normalized = normalizeError(raw, 'anthropic');
    assert.equal(normalized.code, 'RATE_LIMIT_ERROR');
    assert.match(normalized.message, /レート制限エラー/);
  });

  it('404 ステータスコードまたは NoSuchModelError を INVALID_MODEL に分類する', () => {
    const raw = Object.assign(new Error('Model not found'), { statusCode: 404 });
    const normalized = normalizeError(raw, 'google');
    assert.equal(normalized.code, 'INVALID_MODEL');
    assert.match(normalized.message, /モデルエラー/);
  });

  it('コンテキスト長超過メッセージを CONTEXT_LENGTH_EXCEEDED に分類する', () => {
    const raw = new Error('This model maximum context length is 8192 tokens');
    const normalized = normalizeError(raw, 'openrouter');
    assert.equal(normalized.code, 'CONTEXT_LENGTH_EXCEEDED');
    assert.match(normalized.message, /コンテキスト長超過/);
  });

  it('ネットワーク切断や fetch failed を NETWORK_ERROR に分類する', () => {
    const raw = Object.assign(new Error('fetch failed'), { code: 'ECONNREFUSED' });
    const normalized = normalizeError(raw, 'ollama');
    assert.equal(normalized.code, 'NETWORK_ERROR');
    assert.match(normalized.message, /ネットワークエラー/);
  });

  it('500 ステータスを PROVIDER_ERROR に分類する', () => {
    const raw = Object.assign(new Error('Internal Server Error'), { status: 500 });
    const normalized = normalizeError(raw, 'anthropic');
    assert.equal(normalized.code, 'PROVIDER_ERROR');
    assert.match(normalized.message, /プロバイダサーバーエラー/);
  });

  it('応答が空の場合を EMPTY_RESPONSE に分類する', () => {
    const raw = new Error('empty response');
    const normalized = normalizeError(raw);
    assert.equal(normalized.code, 'EMPTY_RESPONSE');
    assert.match(normalized.message, /応答が空でした/);
  });

  it('cause を再帰的に unwrapping して分類する', () => {
    const rootErr = Object.assign(new Error('API key invalid'), { statusCode: 401 });
    const outerErr = new Error('Runner failed', { cause: rootErr });
    const normalized = normalizeError(outerErr, 'openai');
    assert.equal(normalized.code, 'AUTHENTICATION_ERROR');
  });

  it('formatUserMessage の形式を正しく生成する', () => {
    const err = new AimError('テストエラー', { provider: 'anthropic' });
    assert.equal(err.formatUserMessage(), '[anthropic] テストエラー');

    const errNoProv = new AimError('テストエラー');
    assert.equal(errNoProv.formatUserMessage(), 'テストエラー');
  });
});
