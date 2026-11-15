import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pMap, askOnce, runParallel, JOBS_DEFAULT, JOBS_MIN, JOBS_MAX } from '../src/parallel.js';
import { makeEntry, type ResultEntry } from '../src/formatter.js';
import type { RunResult } from '../src/runner.js';

describe('parallel: pMap concurrency controller', () => {
  it('concurrency を超えずに並行実行する', async () => {
    let running = 0;
    let maxRunning = 0;
    const items = [1, 2, 3, 4, 5, 6, 7, 8];

    const results = await pMap(
      items,
      async (n) => {
        running++;
        maxRunning = Math.max(maxRunning, running);
        await new Promise((resolve) => setTimeout(resolve, 10));
        running--;
        return n * 2;
      },
      3
    );

    assert.equal(maxRunning, 3);
    assert.deepEqual(results, [2, 4, 6, 8, 10, 12, 14, 16]);
  });

  it('空配列を渡した場合は即座に空配列を返す', async () => {
    const results = await pMap([], async (x) => x, 4);
    assert.deepEqual(results, []);
  });
});

describe('parallel: askOnce retry & error handling', () => {
  it('1回目失敗・2回目成功でリトライが成功する', async () => {
    let calls = 0;
    const fakeRunner = async (): Promise<RunResult> => {
      calls++;
      if (calls === 1) {
        throw new Error('Temporary connection glitch');
      }
      return { text: '  recovered result  ' };
    };

    const entry = makeEntry({ index: 1, prompt: 'hello', success: false });
    const res = await askOnce({
      provider: 'openai',
      modelId: 'gpt-4o',
      modelAlias: 'gpt-4o',
      prompt: 'hello',
      entry,
      runPromptFn: fakeRunner,
    });

    assert.equal(calls, 2);
    assert.equal(res.success, true);
    assert.equal(res.response, 'recovered result');
  });

  it('2回連続失敗した場合は success: false と正規化エラーを返す', async () => {
    let calls = 0;
    const fakeRunner = async (): Promise<RunResult> => {
      calls++;
      const err = Object.assign(new Error('Rate limit exceeded'), { statusCode: 429 });
      throw err;
    };

    const entry = makeEntry({ index: 1, prompt: 'hello', success: false });
    const res = await askOnce({
      provider: 'anthropic',
      modelId: 'claude-3-5-sonnet',
      modelAlias: 'claude-sonnet',
      prompt: 'hello',
      entry,
      runPromptFn: fakeRunner,
    });

    assert.equal(calls, 2);
    assert.equal(res.success, false);
    assert.match(res.error!, /レート制限エラー/);
  });

  it('応答が空の場合は EMPTY_RESPONSE エラーとして扱う', async () => {
    const fakeRunner = async (): Promise<RunResult> => {
      return { text: '   \n  ' };
    };

    const entry = makeEntry({ index: 1, prompt: 'hello', success: false });
    const res = await askOnce({
      provider: 'openai',
      modelId: 'gpt-4o',
      modelAlias: 'gpt-4o',
      prompt: 'hello',
      entry,
      runPromptFn: fakeRunner,
    });

    assert.equal(res.success, false);
    assert.match(res.error!, /応答が空でした/);
  });
});

describe('parallel: runParallel execution', () => {
  it('複数プロンプトを並行実行し、部分失敗があっても entries を更新する', async () => {
    const fakeRunner = async (
      _provider: string,
      _modelId: string,
      prompt: string | Array<any>
    ): Promise<RunResult> => {
      const lastPrompt = Array.isArray(prompt)
        ? String(prompt[prompt.length - 1]?.content ?? '')
        : prompt;

      if (lastPrompt.includes('fail')) {
        throw new Error('fail prompt error');
      }
      return { text: `response for ${lastPrompt}` };
    };

    const entries: ResultEntry[] = [
      makeEntry({ index: 1, prompt: 'prompt 1', rawPath: 'a.ts', success: false }),
      makeEntry({ index: 2, prompt: 'fail prompt 2', rawPath: 'b.ts', success: false }),
      makeEntry({ index: 3, prompt: 'prompt 3', rawPath: 'c.ts', success: false }),
    ];

    const targets = [
      { index: 0, expandedPrompt: 'prompt 1' },
      { index: 1, expandedPrompt: 'fail prompt 2' },
      { index: 2, expandedPrompt: 'prompt 3' },
    ];

    const results = await runParallel({
      provider: 'openai',
      modelId: 'gpt-4o',
      modelAlias: 'gpt-4o',
      jobs: 2,
      entries,
      targets,
      runPromptFn: fakeRunner,
    });

    assert.equal(results.length, 3);
    assert.equal(results[0].success, true);
    assert.equal(results[0].response, 'response for prompt 1');
    assert.equal(results[0].error, null);

    assert.equal(results[1].success, false);
    assert.equal(results[1].response, null);
    assert.match(results[1].error!, /fail prompt error/);

    assert.equal(results[2].success, true);
    assert.equal(results[2].response, 'response for prompt 3');
    assert.equal(results[2].error, null);
  });

  it('runParallel はジョブごとの session_id と共有 batch_id を保存する', async () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-parallel-log-'));
    try {
      const seenInputs: Array<string | Array<any>> = [];
      const fakeRunner = async (
        _provider: string,
        _modelId: string,
        prompt: string | Array<any>
      ): Promise<RunResult> => {
        seenInputs.push(prompt);
        if (typeof prompt === 'string' && prompt.includes('fail')) {
          throw new Error('fail prompt error');
        }
        return { text: `response for ${String(prompt)}` };
      };

      const entries: ResultEntry[] = [
        makeEntry({ index: 1, prompt: 'prompt 1', rawPath: 'a.ts', success: false }),
        makeEntry({ index: 2, prompt: 'fail prompt 2', rawPath: 'b.ts', success: false }),
        makeEntry({ index: 3, prompt: 'prompt 3', rawPath: 'c.ts', success: false }),
      ];
      const targets = [
        { index: 0, expandedPrompt: 'prompt 1', sessionId: 'session-1' },
        { index: 1, expandedPrompt: 'fail prompt 2', sessionId: 'session-2' },
        { index: 2, expandedPrompt: 'prompt 3', sessionId: 'session-3' },
      ];

      await runParallel({
        provider: 'openai',
        modelId: 'gpt-4o',
        modelAlias: 'gpt-4o',
        jobs: 2,
        entries,
        targets,
        batchId: 'batch-shared',
        logBaseDir: tmpDir,
        runPromptFn: fakeRunner,
      });

      assert.equal(seenInputs.length, 4);
      for (const input of seenInputs) {
        assert.equal(typeof input, 'string');
      }

      const date = new Date().toISOString().slice(0, 10);
      const logPaths = ['session-1', 'session-3'].map((sessionId) =>
        path.join(tmpDir, 'aim2-cli', date, `${sessionId}.jsonl`)
      );
      for (const logPath of logPaths) {
        assert.ok(fs.existsSync(logPath));
      }
      assert.equal(
        fs.existsSync(path.join(tmpDir, 'aim2-cli', date, 'session-2.jsonl')),
        false
      );

      const records = logPaths.flatMap((logPath) =>
        fs
          .readFileSync(logPath, 'utf-8')
          .trim()
          .split('\n')
          .map((line) => JSON.parse(line))
      );
      assert.deepEqual(
        records.map((record) => record.session_id),
        ['session-1', 'session-3']
      );
      assert.deepEqual(
        records.map((record) => record.batch_id),
        ['batch-shared', 'batch-shared']
      );
      assert.deepEqual(
        records.map((record) => record.response),
        ['response for prompt 1', 'response for prompt 3']
      );
      assert.deepEqual(
        records.map((record) => record.prompt),
        ['prompt 1', 'prompt 3']
      );
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('targets が空の場合は何もしない', async () => {
    const entries: ResultEntry[] = [makeEntry({ index: 1, success: false, error: 'initial' })];
    const results = await runParallel({
      provider: 'openai',
      modelId: 'gpt-4o',
      modelAlias: 'gpt-4o',
      entries,
      targets: [],
    });
    assert.equal(results[0].error, 'initial');
  });
});
