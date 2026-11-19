import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  makeEntry,
  formatMarkdown,
  formatJson,
  formatResults,
  type ResultEntry,
} from '../src/formatter.js';

describe('formatter (Output formatting)', () => {
  it('makeEntry はデフォルト値と指定値を正しく設定する', () => {
    const entry1 = makeEntry({ success: true, response: 'hello' });
    assert.equal(entry1.index, 1);
    assert.equal(entry1.prompt, '');
    assert.equal(entry1.path, '');
    assert.equal(entry1.resolved_path, '');
    assert.equal(entry1.success, true);
    assert.equal(entry1.response, 'hello');
    assert.equal(entry1.error, null);

    const entry2 = makeEntry({
      index: 2,
      prompt: 'custom prompt',
      rawPath: 'src/foo.ts',
      resolvedPath: '/abs/src/foo.ts',
      success: false,
      error: 'failed',
    });
    assert.equal(entry2.index, 2);
    assert.equal(entry2.prompt, 'custom prompt');
    assert.equal(entry2.path, 'src/foo.ts');
    assert.equal(entry2.resolved_path, '/abs/src/foo.ts');
    assert.equal(entry2.success, false);
    assert.equal(entry2.response, null);
    assert.equal(entry2.error, 'failed');
  });

  it('formatMarkdown は現行 aim と同等の見出しと本文ブロックを出力する', () => {
    const entries: ResultEntry[] = [
      makeEntry({
        index: 1,
        rawPath: 'a.py',
        resolvedPath: '/abs/a.py',
        success: true,
        response: 'ok-a',
        prompt: '@a.py',
      }),
      makeEntry({
        index: 2,
        rawPath: 'b.py',
        resolvedPath: '/abs/b.py',
        success: false,
        error: 'boom',
        prompt: '@b.py',
      }),
      makeEntry({
        index: 3,
        success: true,
        response: 'ok-c',
        prompt: 'plain question',
      }),
    ];

    const md = formatMarkdown(entries);
    assert.ok(md.includes('## 1 · a.py\n\nok-a\n'));
    assert.ok(md.includes('## 2 · b.py\n\n⚠ エラー: boom\n'));
    assert.ok(md.includes('## 3\n\nok-c\n'));
  });

  it('formatJson は JSON 規格に準拠したインデント付き文字列を返す', () => {
    const entries: ResultEntry[] = [
      makeEntry({
        index: 1,
        rawPath: 'a.py',
        resolvedPath: '/abs/a.py',
        success: true,
        response: 'ok-a',
        prompt: '@a.py',
      }),
      makeEntry({
        index: 2,
        rawPath: 'b.py',
        resolvedPath: '/abs/b.py',
        success: false,
        error: 'boom',
        prompt: '@b.py',
      }),
    ];

    const jsonStr = formatJson(entries);
    const parsed = JSON.parse(jsonStr);
    assert.equal(Array.isArray(parsed), true);
    assert.equal(parsed.length, 2);
    assert.equal(parsed[0].index, 1);
    assert.equal(parsed[0].path, 'a.py');
    assert.equal(parsed[0].success, true);
    assert.equal(parsed[0].response, 'ok-a');
    assert.equal(parsed[1].index, 2);
    assert.equal(parsed[1].path, 'b.py');
    assert.equal(parsed[1].success, false);
    assert.equal(parsed[1].error, 'boom');
  });

  it('formatResults は単発実行（未指定）で応答本文のみを返す', () => {
    const entries = [makeEntry({ success: true, response: 'single response' })];
    const out = formatResults(entries, { parallel: false });
    assert.equal(out, 'single response');
  });

  it('formatResults は単発実行で json 指定時に 1 要素配列を返す', () => {
    const entries = [makeEntry({ success: true, response: 'single response', prompt: 'hi' })];
    const out = formatResults(entries, { format: 'json', parallel: false });
    const parsed = JSON.parse(out);
    assert.equal(parsed.length, 1);
    assert.equal(parsed[0].response, 'single response');
    assert.equal(parsed[0].prompt, 'hi');
  });

  it('formatResults は parallel 実行（format未指定）で markdown を返す', () => {
    const entries = [
      makeEntry({ index: 1, success: true, response: 'resp 1' }),
      makeEntry({ index: 2, success: true, response: 'resp 2' }),
    ];
    const out = formatResults(entries, { parallel: true });
    assert.ok(out.includes('## 1\n\nresp 1\n'));
    assert.ok(out.includes('## 2\n\nresp 2\n'));
  });

  it('formatResults は parallel 実行（format: json）で配列 JSON を返す', () => {
    const entries = [
      makeEntry({ index: 1, success: true, response: 'resp 1' }),
      makeEntry({ index: 2, success: true, response: 'resp 2' }),
    ];
    const out = formatResults(entries, { format: 'json', parallel: true });
    const parsed = JSON.parse(out);
    assert.equal(parsed.length, 2);
    assert.equal(parsed[0].index, 1);
    assert.equal(parsed[1].index, 2);
  });
});
