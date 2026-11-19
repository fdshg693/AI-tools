import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {
  isExplicitPathToken,
  findAtRefs,
  stripAtRefs,
  expandAtRefs,
  tryExpandPrompt,
  AtError,
} from '../src/at-path.js';

describe('at-path (At-path syntax detection and expansion)', () => {
  it('isExplicitPathToken detects explicit path tokens', () => {
    assert.equal(isExplicitPathToken('src/foo.py'), true);
    assert.equal(isExplicitPathToken('src\\foo.py'), true);
    assert.equal(isExplicitPathToken('./a.py'), true);
    assert.equal(isExplicitPathToken('../a.py'), true);
    assert.equal(isExplicitPathToken('~/a.py'), true);
    assert.equal(isExplicitPathToken('C:\\a.py'), true);
    assert.equal(isExplicitPathToken('C:/a.py'), true);
    assert.equal(isExplicitPathToken('foo.py'), false);
    assert.equal(isExplicitPathToken('user'), false);
    assert.equal(isExplicitPathToken('SKILL.md'), false);
  });

  it('finds existing file in prompt', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.writeFileSync(path.join(tmpDir, 'foo.py'), 'x', 'utf-8');
      const refs = findAtRefs('@foo.py を要約して', tmpDir);
      assert.equal(refs.length, 1);
      assert.equal(refs[0].rawPath, 'foo.py');
      assert.equal(refs[0].start, 0);
      assert.equal(refs[0].resolved, path.resolve(tmpDir, 'foo.py'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('handles Japanese particles right after path without space', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      const src = path.join(tmpDir, 'src');
      fs.mkdirSync(src);
      fs.writeFileSync(path.join(src, 'foo.py'), 'x', 'utf-8');

      const text = '@src/foo.pyを要約して';
      const refs = findAtRefs(text, tmpDir);
      assert.equal(refs.length, 1);
      assert.equal(refs[0].rawPath, 'src/foo.py');
      assert.equal(text.slice(refs[0].end), 'を要約して');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('email addresses are not parsed as path', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.deepEqual(findAtRefs('contact foo@gmail.com please', tmpDir), []);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('mentions without existing files are ignored', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.deepEqual(findAtRefs('hey @user hello', tmpDir), []);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('missing bare name is left as is', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.deepEqual(findAtRefs('@foo.py を見て', tmpDir), []);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('directory named foo does not steal @foo.py', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.mkdirSync(path.join(tmpDir, 'foo'));
      assert.deepEqual(findAtRefs('@foo.py です', tmpDir), []);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('prefers foo.py over foo dir when both exist', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.mkdirSync(path.join(tmpDir, 'foo'));
      fs.writeFileSync(path.join(tmpDir, 'foo.py'), 'x', 'utf-8');

      const refs = findAtRefs('@foo.py', tmpDir);
      assert.equal(refs.length, 1);
      assert.equal(refs[0].rawPath, 'foo.py');
      assert.equal(fs.statSync(refs[0].resolved).isFile(), true);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('.gitignore is not cut at dot', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.writeFileSync(path.join(tmpDir, '.gitignore'), '*', 'utf-8');
      const refs = findAtRefs('@.gitignore', tmpDir);
      assert.equal(refs.length, 1);
      assert.equal(refs[0].rawPath, '.gitignore');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('quoted path with spaces', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.writeFileSync(path.join(tmpDir, 'my file.txt'), 'hi', 'utf-8');
      const text = '@"my file.txt"を読んで';
      const refs = findAtRefs(text, tmpDir);
      assert.equal(refs.length, 1);
      assert.equal(refs[0].rawPath, 'my file.txt');
      assert.equal(text.slice(refs[0].end), 'を読んで');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('quoted missing path throws error', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.throws(
        () => findAtRefs('@"no such.txt"', tmpDir),
        (err: Error) => err instanceof AtError && err.message.includes('存在しません')
      );
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('unterminated quote throws error', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.throws(
        () => findAtRefs('@"oops', tmpDir),
        (err: Error) => err instanceof AtError && err.message.includes('引用符')
      );
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('empty quoted path throws error', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.throws(
        () => findAtRefs('@""', tmpDir),
        (err: Error) => err instanceof AtError && err.message.includes('空のパス')
      );
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('missing explicit path throws error', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.throws(
        () => findAtRefs('@src/missing.py を', tmpDir),
        (err: Error) => err instanceof AtError && err.message.includes('存在しません')
      );
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('missing ./ path throws error', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      assert.throws(
        () => findAtRefs('@./nope.py', tmpDir),
        (err: Error) => err instanceof AtError && err.message.includes('存在しません')
      );
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('dot slash existing path works', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.writeFileSync(path.join(tmpDir, 'a.py'), 'x', 'utf-8');
      const refs = findAtRefs('@./a.py', tmpDir);
      assert.equal(refs.length, 1);
      assert.equal(refs[0].rawPath, './a.py');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('multiple refs and stripAtRefs', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.writeFileSync(path.join(tmpDir, 'a.py'), 'a', 'utf-8');
      fs.writeFileSync(path.join(tmpDir, 'b.py'), 'b', 'utf-8');
      const text = '@a.py @b.py を要約';
      const refs = findAtRefs(text, tmpDir);
      assert.deepEqual(refs.map((r) => r.rawPath), ['a.py', 'b.py']);
      assert.equal(stripAtRefs(text, refs), 'を要約');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('expandAtRefs replaces in place', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.writeFileSync(path.join(tmpDir, 'a.py'), 'a', 'utf-8');
      const text = '前 @a.py 後';
      const refs = findAtRefs(text, tmpDir);
      const out = expandAtRefs(text, [{ ref: refs[0], block: 'BLOCK' }]);
      assert.equal(out, '前 BLOCK 後');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('tryExpandPrompt expands prompt with file contents', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-at-test-'));
    try {
      fs.writeFileSync(path.join(tmpDir, 'a.py'), 'content-of-a', 'utf-8');
      const result = tryExpandPrompt('@a.py を確認して', tmpDir);
      assert.equal(result.error, null);
      assert(result.expanded !== null);
      assert(result.expanded.includes('--- FILE: a.py ---'));
      assert(result.expanded.includes('content-of-a'));
      assert(result.expanded.includes('を確認して'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
