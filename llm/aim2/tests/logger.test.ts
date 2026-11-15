import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {
  newTraceId,
  resolveTrace,
  sanitizeToolName,
  getLogPath,
  appendLog,
  buildLogRecord,
  UNKNOWN_TRACE_TOOL,
  newSessionId,
  encodeSessionIdForFilename,
} from '../src/logger.js';

describe('logger (Trace and JSONL logging)', () => {
  it('newTraceId は 32 桁の hex 文字列を生成する', () => {
    const id1 = newTraceId();
    const id2 = newTraceId();
    assert.equal(id1.length, 32);
    assert.match(id1, /^[0-9a-f]{32}$/);
    assert.notEqual(id1, id2);
  });

  it('newSessionId は固定長の時刻順 ID を生成する', () => {
    const now = Date.now();
    const first = newSessionId(now);
    const second = newSessionId(now + 1);
    const sameTime = newSessionId(now + 1);

    assert.match(first, /^s\d{13}-[0-9a-f]{32}$/);
    assert.equal(first.length, second.length);
    assert(first < second);
    assert(second !== sameTime);
    assert.equal(sameTime.length, first.length);
  });

  it('encodeSessionIdForFilename は明示 ID を安全にエンコードする', () => {
    assert.equal(encodeSessionIdForFilename('project-a_1'), 'project-a_1');
    assert.notEqual(encodeSessionIdForFilename('../project'), '../project');
    assert.notEqual(encodeSessionIdForFilename('CON'), 'CON');
    assert.match(encodeSessionIdForFilename('日本語'), /^~[A-Za-z0-9_-]+$/);
  });

  it('resolveTrace は既存の trace_id を保持し、無ければ生成する', () => {
    const withId = resolveTrace({ trace_id: 'custom-id', tool: 'my-tool' });
    assert.equal(withId.trace_id, 'custom-id');
    assert.equal(withId.tool, 'my-tool');

    const withoutId = resolveTrace({ tool: 'my-tool' });
    assert.equal(withoutId.tool, 'my-tool');
    assert.equal(typeof withoutId.trace_id, 'string');
    assert.equal(withoutId.trace_id!.length, 32);

    const empty = resolveTrace(null);
    assert.equal(typeof empty.trace_id, 'string');
    assert.equal(empty.trace_id!.length, 32);
  });

  it('sanitizeToolName は安全なフォルダ名に変換する', () => {
    assert.equal(sanitizeToolName('aim2-cli'), 'aim2-cli');
    assert.equal(sanitizeToolName(''), UNKNOWN_TRACE_TOOL);
    assert.equal(sanitizeToolName('   '), UNKNOWN_TRACE_TOOL);
    assert.equal(sanitizeToolName('../../evil/path'), 'evil_path');
    assert.equal(sanitizeToolName('tool:name?*'), 'tool_name');
  });

  it('getLogPath は日付とツール名に基づきログパスを決定する', () => {
    const record = buildLogRecord({
      model: 'gpt-4o',
      prompt: 'hello',
      trace: { tool: 'test-tool' },
      timestamp: '2026-09-08T12:00:00.000Z',
    });
    const logPath = getLogPath(record, '/tmp/test-logs');
    assert.equal(
      path.normalize(logPath),
      path.normalize('/tmp/test-logs/test-tool/2026-09-08.jsonl')
    );

    const recordUnknown = buildLogRecord({
      model: 'gpt-4o',
      prompt: 'hello',
      timestamp: '2026-09-08T12:00:00.000Z',
    });
    const logPathUnknown = getLogPath(recordUnknown, '/tmp/test-logs');
    assert.equal(
      path.normalize(logPathUnknown),
      path.normalize('/tmp/test-logs/unknown/2026-09-08.jsonl')
    );
  });

  it('session_id がある場合は日付ディレクトリとセッションファイルへ保存する', () => {
    const record = buildLogRecord({
      model: 'gpt-4o',
      prompt: 'hello',
      sessionId: 'project-a',
      batchId: 'batch-1',
      trace: { tool: 'test-tool' },
      timestamp: '2026-09-08T12:00:00.000Z',
    });
    const logPath = getLogPath(record, '/tmp/test-logs');
    assert.equal(
      path.normalize(logPath),
      path.normalize('/tmp/test-logs/test-tool/2026-09-08/project-a.jsonl')
    );
  });

  it('appendLog は JSONL ファイルを作成・追記する', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-log-test-'));
    try {
      const record1 = buildLogRecord({
        model: 'claude-sonnet',
        provider: 'anthropic',
        prompt: 'test prompt 1',
        response: 'test response 1',
        usage: { promptTokens: 10, completionTokens: 20, totalTokens: 30 },
        trace: { tool: 'cli-test', trace_id: 'trace-1' },
        threadId: 'thread-1',
        timestamp: '2026-09-08T10:00:00.000Z',
      });
      const record2 = buildLogRecord({
        model: 'gpt-4o',
        provider: 'openai',
        prompt: 'test prompt 2',
        response: 'test response 2',
        trace: { tool: 'cli-test', trace_id: 'trace-2' },
        threadId: 'thread-1',
        timestamp: '2026-09-08T10:01:00.000Z',
      });

      const writtenPath1 = appendLog(record1, tmpDir);
      const writtenPath2 = appendLog(record2, tmpDir);

      assert.equal(writtenPath1, writtenPath2);
      assert.ok(fs.existsSync(writtenPath1));

      const content = fs.readFileSync(writtenPath1, 'utf-8');
      const lines = content.trim().split('\n');
      assert.equal(lines.length, 2);

      const parsed1 = JSON.parse(lines[0]);
      assert.equal(parsed1.model, 'claude-sonnet');
      assert.equal(parsed1.provider, 'anthropic');
      assert.equal(parsed1.prompt_tokens, 10);
      assert.equal(parsed1.completion_tokens, 20);
      assert.equal(parsed1.total_tokens, 30);
      assert.equal(parsed1.trace.tool, 'cli-test');
      assert.equal(parsed1.trace.trace_id, 'trace-1');
      assert.equal(parsed1.thread_id, 'thread-1');
      assert.equal(parsed1.batch_id, null);
      assert.equal(parsed1.response, 'test response 1');

      const parsed2 = JSON.parse(lines[1]);
      assert.equal(parsed2.model, 'gpt-4o');
      assert.equal(parsed2.provider, 'openai');
      assert.equal(parsed2.prompt_tokens, null);
      assert.equal(parsed2.thread_id, 'thread-1');
      assert.equal(parsed2.response, 'test response 2');
      assert.equal(parsed2.batch_id, null);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
