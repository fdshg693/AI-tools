import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { appendLog, buildLogRecord } from '../src/logger.js';
import {
  buildPromptInput,
  buildThreadMessages,
  loadSessionHistory,
  loadThreadHistory,
  resolveSessionId,
  resolveThreadId,
} from '../src/thread.js';
import { AimError } from '../src/errors.js';

describe('thread', () => {
  it('resolveSessionId は未指定時に時刻順 ID を自動生成する', () => {
    const resolved = resolveSessionId();
    assert.equal(resolved.generated, true);
    assert.match(resolved.sessionId, /^s\d{13}-[0-9a-f]{32}$/);
  });

  it('resolveSessionId は明示指定を trim して保持する', () => {
    const resolved = resolveSessionId('  local-thread  ');
    assert.equal(resolved.generated, false);
    assert.equal(resolved.sessionId, 'local-thread');
  });

  it('resolveThreadId は旧 API として session ID を返す', () => {
    const resolved = resolveThreadId('local-thread');
    assert.equal(resolved.threadId, 'local-thread');
  });

  it('resolveSessionId は空文字や制御文字を拒否する', () => {
    assert.throws(() => resolveSessionId('   '), (err: unknown) => {
      assert(err instanceof AimError);
      assert.match(err.message, /空でない文字列/);
      return true;
    });

    assert.throws(() => resolveSessionId('bad\nid'), (err: unknown) => {
      assert(err instanceof AimError);
      assert.match(err.message, /制御文字/);
      return true;
    });
  });

  it('buildThreadMessages は user/assistant の交互メッセージ列を返す', () => {
    const messages = buildThreadMessages([
      { prompt: 'first', response: 'reply 1', timestamp: '2026-09-15T00:00:00.000Z' },
      { prompt: 'second', response: 'reply 2', timestamp: '2026-09-15T00:01:00.000Z' },
    ]);

    assert.deepEqual(messages, [
      { role: 'user', content: 'first' },
      { role: 'assistant', content: 'reply 1' },
      { role: 'user', content: 'second' },
      { role: 'assistant', content: 'reply 2' },
    ]);
  });

  it('buildPromptInput は履歴なしでは従来どおり prompt 文字列を返す', () => {
    const input = buildPromptInput([], 'current question');
    assert.equal(input, 'current question');
  });

  it('buildPromptInput は履歴ありでは messages に現在の user prompt を追加する', () => {
    const input = buildPromptInput(
      [{ prompt: 'first', response: 'reply 1', timestamp: '2026-09-15T00:00:00.000Z' }],
      'second'
    );

    assert.deepEqual(input, [
      { role: 'user', content: 'first' },
      { role: 'assistant', content: 'reply 1' },
      { role: 'user', content: 'second' },
    ]);
  });

  it('loadThreadHistory は複数ファイル・複数 trace tool を横断し、旧形式や不正行を無視する', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-thread-test-'));
    try {
      appendLog(
        buildLogRecord({
          model: 'gpt-4o',
          prompt: 'turn 2',
          response: 'answer 2',
          threadId: 'thread-a',
          trace: { tool: 'z-tool' },
          timestamp: '2026-09-15T00:02:00.000Z',
        }),
        tmpDir
      );
      appendLog(
        buildLogRecord({
          model: 'gpt-4o',
          prompt: 'turn 1',
          response: 'answer 1',
          threadId: 'thread-a',
          trace: { tool: 'a-tool' },
          timestamp: '2026-09-15T00:01:00.000Z',
        }),
        tmpDir
      );
      appendLog(
        buildLogRecord({
          model: 'gpt-4o',
          prompt: 'other thread',
          response: 'ignored',
          threadId: 'thread-b',
          trace: { tool: 'a-tool' },
          timestamp: '2026-09-15T00:03:00.000Z',
        }),
        tmpDir
      );

      const legacyPath = path.join(tmpDir, 'legacy-tool', '2026-09-15.jsonl');
      fs.mkdirSync(path.dirname(legacyPath), { recursive: true });
      fs.writeFileSync(
        legacyPath,
        [
          JSON.stringify({
            timestamp: '2026-09-15T00:00:00.000Z',
            model: 'gpt-4o',
            prompt: 'legacy prompt without thread',
            response: 'legacy answer',
          }),
          JSON.stringify({
            timestamp: '2026-09-15T00:00:30.000Z',
            model: 'gpt-4o',
            prompt: 'batch record must not become history',
            response: 'ignored',
            session_id: 'thread-a',
          }),
          '{"bad-json"',
          JSON.stringify({
            timestamp: '2026-09-15T00:04:00.000Z',
            model: 'gpt-4o',
            prompt: 'missing response',
            thread_id: 'thread-a',
            response: '',
          }),
          '',
        ].join('\n'),
        'utf-8'
      );

      const history = loadThreadHistory('thread-a', tmpDir);
      assert.deepEqual(history, [
        { prompt: 'turn 1', response: 'answer 1', timestamp: '2026-09-15T00:01:00.000Z' },
        { prompt: 'turn 2', response: 'answer 2', timestamp: '2026-09-15T00:02:00.000Z' },
      ]);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('loadThreadHistory は未知の thread_id で空配列を返す', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-thread-empty-'));
    try {
      const history = loadThreadHistory('unknown-thread', tmpDir);
      assert.deepEqual(history, []);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('loadSessionHistory は日付またぎのセッションファイルを結合し、旧ログ重複を除外する', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-session-test-'));
    try {
      appendLog(
        buildLogRecord({
          model: 'gpt-4o',
          prompt: 'first',
          response: 'answer 1',
          sessionId: 'session-cross-day',
          trace: { tool: 'a-tool', trace_id: 'trace-1' },
          timestamp: '2026-09-15T23:59:00.000Z',
        }),
        tmpDir
      );
      appendLog(
        buildLogRecord({
          model: 'gpt-4o',
          prompt: 'second',
          response: 'answer 2',
          sessionId: 'session-cross-day',
          trace: { tool: 'z-tool', trace_id: 'trace-2' },
          timestamp: '2026-09-16T00:01:00.000Z',
        }),
        tmpDir
      );

      const legacyPath = path.join(tmpDir, 'legacy-tool', '2026-09-16.jsonl');
      fs.mkdirSync(path.dirname(legacyPath), { recursive: true });
      fs.writeFileSync(
        legacyPath,
        JSON.stringify({
          timestamp: '2026-09-16T00:01:00.000Z',
          prompt: 'second',
          response: 'answer 2',
          thread_id: 'session-cross-day',
          trace: { trace_id: 'trace-2' },
        }),
        'utf8'
      );

      assert.deepEqual(loadSessionHistory('session-cross-day', tmpDir), [
        { prompt: 'first', response: 'answer 1', timestamp: '2026-09-15T23:59:00.000Z' },
        { prompt: 'second', response: 'answer 2', timestamp: '2026-09-16T00:01:00.000Z' },
      ]);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
