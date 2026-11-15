import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  preprocessArgv,
  parseCliArgs,
  printModelList,
  printAiHelp,
  printHelp,
  printThreadId,
} from '../src/cli.js';
import { AimError } from '../src/errors.js';

describe('cli (CLI interface and argument parsing)', () => {
  it('preprocessArgv expands consecutive prompt arguments into separate --prompt', () => {
    const { cleanedArgv } = preprocessArgv([
      '--parallel',
      '--prompt',
      'question A',
      'question B',
      '-m',
      'gpt-4o',
    ]);
    assert.deepEqual(cleanedArgv, [
      '--parallel',
      '--prompt',
      'question A',
      '--prompt',
      'question B',
      '-m',
      'gpt-4o',
    ]);
  });

  it('parseCliArgs parses prompt, model, flags and positionals', () => {
    const opts = parseCliArgs([
      'extra',
      'words',
      '-m',
      'claude-sonnet',
      '--prompt',
      'first prompt',
      '-p',
      'second prompt',
    ]);

    assert.equal(opts.model, 'claude-sonnet');
    assert.deepEqual(opts.prompt, ['first prompt', 'second prompt']);
    assert.deepEqual(opts.positionals, ['extra', 'words']);
  });

  it('parseCliArgs parses --parallel, --jobs, --format and --trace-tool', () => {
    const opts = parseCliArgs([
      '--parallel',
      '--jobs',
      '8',
      '--format',
      'json',
      '--trace-tool',
      'custom-tool',
      '--prompt',
      'prompt A',
      'prompt B',
    ]);

    assert.equal(opts.parallel, true);
    assert.equal(opts.jobs, 8);
    assert.equal(opts.format, 'json');
    assert.equal(opts['trace-tool'], 'custom-tool');
    assert.deepEqual(opts.prompt, ['prompt A', 'prompt B']);
  });

  it('parseCliArgs parses an explicit --session-id for single execution', () => {
    const opts = parseCliArgs(['--session-id', 'session-123', '--prompt', 'hello']);
    assert.equal(opts['session-id'], 'session-123');
    assert.equal(opts.parallel, false);
  });

  it('parseCliArgs keeps --thread-id as a session-id alias', () => {
    const opts = parseCliArgs(['--thread-id', 'thread-123', '--prompt', 'hello']);
    assert.equal(opts['thread-id'], 'thread-123');
  });

  it('parseCliArgs throws error when --jobs is used without --parallel', () => {
    assert.throws(
      () => parseCliArgs(['--jobs', '4', '--prompt', 'hello']),
      (err: unknown) => {
        return err instanceof AimError && err.message.includes('--jobs は --parallel と一緒に指定してください');
      }
    );
  });

  it('parseCliArgs rejects --thread-id with --parallel', () => {
    assert.throws(
      () => parseCliArgs(['--parallel', '--thread-id', 'thread-123', '--prompt', 'hello']),
      (err: unknown) => {
        return (
          err instanceof AimError &&
          err.message.includes('--thread-id は --parallel と一緒に指定できません')
        );
      }
    );
  });

  it('parseCliArgs rejects both session ID option names together', () => {
    assert.throws(
      () =>
        parseCliArgs([
          '--session-id',
          'session-123',
          '--thread-id',
          'thread-123',
          '--prompt',
          'hello',
        ]),
      (err: unknown) =>
        err instanceof AimError && err.message.includes('同時に指定できません')
    );
  });

  it('parseCliArgs throws error when --jobs is out of range', () => {
    assert.throws(
      () => parseCliArgs(['--parallel', '--jobs', '0', '--prompt', 'hello']),
      (err: unknown) => {
        return err instanceof AimError && err.message.includes('1〜10 の範囲');
      }
    );
    assert.throws(
      () => parseCliArgs(['--parallel', '--jobs', '11', '--prompt', 'hello']),
      (err: unknown) => {
        return err instanceof AimError && err.message.includes('1〜10 の範囲');
      }
    );
  });

  it('parseCliArgs throws error when --format is invalid', () => {
    assert.throws(
      () => parseCliArgs(['--format', 'yaml', '--prompt', 'hello']),
      (err: unknown) => {
        return err instanceof AimError && err.message.includes("'markdown' または 'json'");
      }
    );
  });

  it('parseCliArgs recognizes --ai-help and --list-models', () => {
    const opts = parseCliArgs(['--ai-help', '--list-models', '--cost']);
    assert.equal(opts['ai-help'], true);
    assert.equal(opts['list-models'], true);
    assert.equal(opts.cost, true);
  });

  it('printModelList prints formatted model list', () => {
    const lines: string[] = [];
    const origLog = console.log;
    console.log = (...args: unknown[]) => lines.push(args.join(' '));
    try {
      printModelList('gpt-4o', {
        'gpt-4o': { provider: 'openai', id: 'gpt-4o', enable: true },
        'claude-3-5': { provider: 'anthropic', id: 'claude-3-5-sonnet', enable: true },
        disabled: { provider: 'google', id: 'gemini', enable: false },
      });
      const output = lines.join('\n');
      assert(output.includes('gpt-4o'));
      assert(output.includes('(default)'));
      assert(output.includes('claude-3-5'));
      assert(!output.includes('disabled'));
    } finally {
      console.log = origLog;
    }
  });

  it('printAiHelp prints default model and descriptions', () => {
    const lines: string[] = [];
    const origLog = console.log;
    console.log = (...args: unknown[]) => lines.push(args.join(' '));
    try {
      printAiHelp('gpt-4o', {
        'gpt-4o': {
          provider: 'openai',
          id: 'gpt-4o',
          description: 'High intelligence flagship',
          enable: true,
        },
      });
      const output = lines.join('\n');
      assert(output.includes('デフォルトモデル: gpt-4o'));
      assert(output.includes('High intelligence flagship'));
    } finally {
      console.log = origLog;
    }
  });

  it('printHelp includes session ID options and execution options', () => {
    const lines: string[] = [];
    const origLog = console.log;
    console.log = (...args: unknown[]) => lines.push(args.join(' '));
    try {
      printHelp();
      const output = lines.join('\n');
      assert(output.includes('--parallel'));
      assert(output.includes('--jobs'));
      assert(output.includes('--format'));
      assert(output.includes('--trace-tool'));
      assert(output.includes('--session-id'));
      assert(output.includes('--thread-id'));
      assert(output.includes('--full-content-names'));
    } finally {
      console.log = origLog;
    }
  });

  it('printThreadId writes the resolved ID to stderr', () => {
    const lines: string[] = [];
    const origError = console.error;
    console.error = (...args: unknown[]) => lines.push(args.join(' '));
    try {
      printThreadId('thread-xyz');
      assert.deepEqual(lines, ['session_id: thread-xyz']);
    } finally {
      console.error = origError;
    }
  });
});
