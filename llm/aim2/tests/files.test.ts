import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {
  parseFullContentNames,
  formatInlineBlock,
  readTextOrError,
} from '../src/files.js';

describe('files (File and Directory operations)', () => {
  it('parseFullContentNames parses comma-separated names', () => {
    assert.equal(parseFullContentNames(undefined), null);
    assert.equal(parseFullContentNames(null), null);
    const parsed = parseFullContentNames('SKILL.md, README.md');
    assert.deepEqual(Array.from(parsed || []).sort(), ['README.md', 'SKILL.md']);
    assert.equal(parseFullContentNames('')?.size, 0);
  });

  it('readTextOrError reads existing text file', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const filePath = path.join(tmpDir, 'foo.py');
      fs.writeFileSync(filePath, 'hello', 'utf-8');
      const { content, error } = readTextOrError(filePath);
      assert.equal(error, null);
      assert.equal(content, 'hello');
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('readTextOrError returns error for missing path', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const filePath = path.join(tmpDir, 'nope.py');
      const { content, error } = readTextOrError(filePath);
      assert.equal(content, null);
      assert(error?.includes('存在しません'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('readTextOrError detects binary file', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const filePath = path.join(tmpDir, 'x.bin');
      fs.writeFileSync(filePath, Buffer.from([0, 1, 2]));
      const { content, error } = readTextOrError(filePath);
      assert.equal(content, null);
      assert(error?.includes('バイナリ'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('readTextOrError detects invalid UTF-8', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const filePath = path.join(tmpDir, 'x.txt');
      fs.writeFileSync(filePath, Buffer.from([0xff, 0xfe]));
      const { content, error } = readTextOrError(filePath);
      assert.equal(content, null);
      assert(error?.includes('UTF-8'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('readTextOrError renders directory tree and contents, excluding ignored dirs', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const root = path.join(tmpDir, 'skill');
      fs.mkdirSync(root);
      fs.writeFileSync(path.join(root, 'SKILL.md'), 'skill-body', 'utf-8');

      const sub = path.join(root, 'sub');
      fs.mkdirSync(sub);
      fs.writeFileSync(path.join(sub, 'note.txt'), 'note-body', 'utf-8');

      const git = path.join(root, '.git');
      fs.mkdirSync(git);
      fs.writeFileSync(path.join(git, 'config'), 'secret', 'utf-8');

      const { content, error } = readTextOrError(root);
      assert.equal(error, null);
      assert(content !== null);
      assert(content.includes('ディレクトリツリー:'));
      assert(content.includes('SKILL.md'));
      assert(content.includes('note.txt'));
      assert(content.includes('skill-body'));
      assert(content.includes('note-body'));
      assert(!content.includes('.git'));
      assert(!content.includes('secret'));
      assert(content.includes('--- FILE: SKILL.md ---'));
      assert(content.includes('--- FILE: sub/note.txt ---'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('readTextOrError with fullContentNames omits other files', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const root = path.join(tmpDir, 'skill');
      fs.mkdirSync(root);
      fs.writeFileSync(path.join(root, 'SKILL.md'), 'skill-body', 'utf-8');
      fs.writeFileSync(path.join(root, 'other.py'), 'other-body', 'utf-8');

      const { content, error } = readTextOrError(root, new Set(['SKILL.md']));
      assert.equal(error, null);
      assert(content !== null);
      assert(content.includes('skill-body'));
      assert(content.includes('--- FILE: SKILL.md ---'));
      assert(!content.includes('other-body'));
      assert(!content.includes('--- FILE: other.py ---'));
      assert(content.includes('内容省略（対象外ファイル）'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('readTextOrError skips binary files in directory tree', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const root = path.join(tmpDir, 'd');
      fs.mkdirSync(root);
      fs.writeFileSync(path.join(root, 'ok.txt'), 'ok', 'utf-8');
      fs.writeFileSync(path.join(root, 'x.bin'), Buffer.from([0, 1]));

      const { content, error } = readTextOrError(root);
      assert.equal(error, null);
      assert(content !== null);
      assert(content.includes('ok'));
      assert(content.includes('読み込みスキップ'));
      assert(!content.includes('--- FILE: x.bin ---'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });

  it('formatInlineBlock distinguishes FILE and DIR', () => {
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-files-test-'));
    try {
      const filePath = path.join(tmpDir, 'a.py');
      fs.writeFileSync(filePath, 'x', 'utf-8');
      const dirPath = path.join(tmpDir, 'd');
      fs.mkdirSync(dirPath);

      assert(formatInlineBlock('a.py', filePath, 'x').startsWith('--- FILE: a.py ---'));
      assert(formatInlineBlock('d', dirPath, 'tree').startsWith('--- DIR: d ---'));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
