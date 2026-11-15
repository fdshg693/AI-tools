import { parseArgs } from 'node:util';
import process from 'node:process';
import {
  loadDotenv,
  loadModels,
  resolveModel,
  ConfigError,
  readPackageVersion,
} from './config.js';
import { tryExpandPrompt, AtError } from './at-path.js';
import { parseFullContentNames } from './files.js';
import { runPrompt, RunnerError } from './runner.js';
import { normalizeError, AimError } from './errors.js';
import { appendLog, buildLogRecord, resolveTrace } from './logger.js';
import { buildPromptInput, loadSessionHistory, resolveSessionId } from './thread.js';
import { makeEntry, formatResults, type ResultEntry, type OutputFormat } from './formatter.js';
import {
  getModelCost,
  formatCostText,
  formatCostJson,
  PricingError,
} from './pricing.js';
import {
  runParallel,
  JOBS_MIN,
  JOBS_MAX,
  JOBS_DEFAULT,
  type ParallelTarget,
} from './parallel.js';

export interface CliOptions {
  help?: boolean;
  version?: boolean;
  'list-models'?: boolean;
  'ai-help'?: boolean;
  cost?: boolean;
  model?: string;
  prompt?: string[];
  parallel?: boolean;
  jobs?: number;
  format?: OutputFormat;
  'trace-tool'?: string;
  'session-id'?: string;
  'thread-id'?: string;
  'full-content-names'?: string;
  positionals: string[];
}

/**
 * 生の process.argv を前処理し、
 * --prompt A B のような複数連続引数を --prompt A --prompt B に正規化する
 */
export function preprocessArgv(argv: string[]): {
  cleanedArgv: string[];
} {
  // --prompt / -p 直後の複数引数（ハイフンで始まらないもの）を展開
  const cleaned: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--prompt' || arg === '-p') {
      cleaned.push(arg);
      // 1 つ目のプロンプト引数
      if (i + 1 < argv.length) {
        cleaned.push(argv[++i]);
      }
      // 2 つ目以降の連続する非オプション引数を --prompt <val> として追加
      while (i + 1 < argv.length && !argv[i + 1].startsWith('-')) {
        cleaned.push('--prompt', argv[++i]);
      }
    } else {
      cleaned.push(arg);
    }
  }

  return { cleanedArgv: cleaned };
}

/**
 * 引数をパースしてバリデーションする
 */
export function parseCliArgs(argv = process.argv.slice(2)): CliOptions {
  const { cleanedArgv } = preprocessArgv(argv);

  const options = {
    help: { type: 'boolean', short: 'h' },
    version: { type: 'boolean', short: 'v' },
    'list-models': { type: 'boolean' },
    'ai-help': { type: 'boolean' },
    cost: { type: 'boolean' },
    model: { type: 'string', short: 'm' },
    prompt: { type: 'string', short: 'p', multiple: true },
    parallel: { type: 'boolean' },
    jobs: { type: 'string' },
    format: { type: 'string' },
    'trace-tool': { type: 'string' },
    'session-id': { type: 'string' },
    'thread-id': { type: 'string' },
    'full-content-names': { type: 'string' },
  } as const;

  const parsed = parseArgs({
    args: cleanedArgv,
    options,
    allowPositionals: true,
    strict: false,
  });

  // jobs バリデーション
  let jobs: number | undefined = undefined;
  if (parsed.values.jobs !== undefined) {
    const parsedJobs = Number(parsed.values.jobs);
    if (!Number.isInteger(parsedJobs) || parsedJobs < JOBS_MIN || parsedJobs > JOBS_MAX) {
      throw new AimError(
        `--jobs は ${JOBS_MIN}〜${JOBS_MAX} の範囲で指定してください: ${parsed.values.jobs}`,
        { code: 'CONFIG_ERROR' }
      );
    }
    jobs = parsedJobs;
  }

  if (jobs !== undefined && !parsed.values.parallel) {
    throw new AimError('--jobs は --parallel と一緒に指定してください', {
      code: 'CONFIG_ERROR',
    });
  }

  if (parsed.values['session-id'] !== undefined && parsed.values['thread-id'] !== undefined) {
    throw new AimError('--session-id と --thread-id は同時に指定できません', {
      code: 'CONFIG_ERROR',
    });
  }

  if (
    parsed.values.parallel &&
    (typeof parsed.values['session-id'] === 'string' ||
      typeof parsed.values['thread-id'] === 'string')
  ) {
    throw new AimError(
      '--session-id/--thread-id は --parallel と一緒に指定できません。並列ジョブごとに別の session ID が自動発行されます',
      { code: 'CONFIG_ERROR' }
    );
  }

  // format バリデーション
  let format: OutputFormat | undefined = undefined;
  if (parsed.values.format !== undefined) {
    if (parsed.values.format !== 'markdown' && parsed.values.format !== 'json') {
      throw new AimError(
        `--format は 'markdown' または 'json' を指定してください: ${parsed.values.format}`,
        { code: 'CONFIG_ERROR' }
      );
    }
    format = parsed.values.format as OutputFormat;
  }

  return {
    help: Boolean(parsed.values.help),
    version: Boolean(parsed.values.version),
    'list-models': Boolean(parsed.values['list-models']),
    'ai-help': Boolean(parsed.values['ai-help']),
    cost: Boolean(parsed.values.cost),
    model: typeof parsed.values.model === 'string' ? parsed.values.model : undefined,
    prompt: Array.isArray(parsed.values.prompt)
      ? (parsed.values.prompt as string[])
      : undefined,
    parallel: Boolean(parsed.values.parallel),
    jobs,
    format,
    'trace-tool':
      typeof parsed.values['trace-tool'] === 'string' ? parsed.values['trace-tool'] : undefined,
    'session-id':
      typeof parsed.values['session-id'] === 'string' ? parsed.values['session-id'] : undefined,
    'thread-id':
      typeof parsed.values['thread-id'] === 'string' ? parsed.values['thread-id'] : undefined,
    'full-content-names':
      typeof parsed.values['full-content-names'] === 'string'
        ? parsed.values['full-content-names']
        : undefined,
    positionals: parsed.positionals,
  };
}

export function printHelp(): void {
  console.log(`aim2 - 複数プロバイダ対応 AI モデル呼び出し CLI

使い方:
  aim2 [オプション] [プロンプト...]
  aim2 --prompt "プロンプト"
  aim2 --prompt "@src/foo.ts を要約して"
  aim2 --parallel --prompt "@a.py 要約して" "@b.py 要約して"
  echo "プロンプト" | aim2

オプション:
  -p, --prompt <text>            プロンプトを指定（複数指定は --parallel が必要）
  -m, --model <alias>            使用するモデル略記（省略時: models.json の default）
  --parallel                     複数のプロンプトを並列に実行する
  --jobs <number>                並列実行数（${JOBS_MIN}〜${JOBS_MAX}、省略時: ${JOBS_DEFAULT}。--parallel 専用）
  --format <markdown|json>       出力形式（未指定かつ単発時は本文のみ、--parallel 時は markdown）
  --trace-tool <name>            トレースログの分類フォルダ名（デフォルト: aim2-cli）
  --session-id <id>              ローカルな会話継続用 session ID（--parallel とは併用不可）
  --thread-id <id>               --session-id の互換エイリアス
  --cost                         指定モデルの入出力単価（$/M tokens）を表示して終了
  --list-models                  利用可能なモデル略記とプロバイダ一覧を表示
  --ai-help                      エージェント向けに使い方・モデル一覧・説明を表示
  --full-content-names <names>   ディレクトリ @path で全内容を含めるファイル名のカンマ区切り
  -v, --version                  バージョン情報を表示
  -h, --help                     このヘルプを表示

例:
  aim2 --prompt "フランスの首都は？"
  aim2 --cost
  aim2 --cost --model glm-5.3-flash
  aim2 -m gpt-4o --prompt "@src/index.ts をレビューして"
  aim2 --session-id project-a --prompt "前回の続きで直して"
  aim2 --parallel --prompt "質問A" "質問B"
  aim2 --parallel --format json --prompt "@a.py 要約" "@b.py 要約"
  echo "コードをリファクタリングして" | aim2 -m claude-sonnet
`);
}

export function printSessionId(sessionId: string, label = 'session_id'): void {
  console.error(`${label}: ${sessionId}`);
}

/** @deprecated 出力ラベルは session_id に統一する。 */
export function printThreadId(sessionId: string, label = 'session_id'): void {
  printSessionId(sessionId, label);
}

export function printAiHelp(
  defaultAlias: string,
  models: Record<string, { provider: string; id: string; description: string; enable: boolean }>
): void {
  printHelp();
  console.log(`デフォルトモデル: ${defaultAlias}\n`);
  console.log('利用可能なモデル:');
  const entries = Object.entries(models).filter(([, spec]) => spec.enable);
  const maxAliasLen = Math.max(...entries.map(([alias]) => alias.length), 5);
  const maxProviderLen = Math.max(...entries.map(([, spec]) => spec.provider.length), 8);

  for (const [alias, spec] of entries) {
    const isDefault = alias === defaultAlias ? '  [default]' : '';
    console.log(
      `${alias.padEnd(maxAliasLen)}  ${spec.provider.padEnd(maxProviderLen)}  ${spec.id}${isDefault}`
    );
    console.log(`  ${spec.description}`);
  }
}

export function printModelList(
  defaultAlias: string,
  models: Record<string, { provider: string; id: string; enable: boolean }>
): void {
  const entries = Object.entries(models).filter(([, spec]) => spec.enable);
  const maxAliasLen = Math.max(...entries.map(([alias]) => alias.length), 5);
  const maxProviderLen = Math.max(...entries.map(([, spec]) => spec.provider.length), 8);

  console.log(
    `${'ALIAS'.padEnd(maxAliasLen)}  ${'PROVIDER'.padEnd(maxProviderLen)}  ${'MODEL ID'}`
  );
  console.log('-'.repeat(maxAliasLen + maxProviderLen + 35));

  for (const [alias, spec] of entries) {
    const isDefault = alias === defaultAlias ? '  (default)' : '';
    console.log(
      `${alias.padEnd(maxAliasLen)}  ${spec.provider.padEnd(maxProviderLen)}  ${spec.id}${isDefault}`
    );
  }
}

/**
 * 標準入力をすべて読み込むヘルパー
 */
async function readAllStdin(): Promise<string> {
  if (process.stdin.isTTY) {
    return '';
  }
  return new Promise<string>((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf-8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => {
      resolve(data);
    });
    process.stdin.on('error', (err) => {
      reject(err);
    });
  });
}

export async function main(): Promise<void> {
  const options = parseCliArgs();

  // --help
  if (options.help) {
    printHelp();
    return;
  }

  // -v, --version
  if (options.version) {
    console.log(`aim2 ${readPackageVersion()}`);
    return;
  }

  // 固定パスの .env をロード
  loadDotenv();

  // models.json をロード
  const modelsConfig = loadModels();

  // --list-models
  if (options['list-models']) {
    printModelList(modelsConfig.default, modelsConfig.models);
    return;
  }

  // --ai-help
  if (options['ai-help']) {
    printAiHelp(modelsConfig.default, modelsConfig.models);
    return;
  }

  // モデル解決
  const resolved = resolveModel(modelsConfig, options.model);

  // --cost
  if (options.cost) {
    try {
      const cost = await getModelCost(resolved.spec.provider, resolved.spec.id);
      if (options.format === 'json') {
        console.log(formatCostJson(resolved.alias, cost));
      } else {
        console.log(formatCostText(resolved.alias, cost));
      }
      return;
    } catch (err: any) {
      console.error(`エラー: ${err instanceof PricingError ? err.message : String(err)}`);
      process.exit(1);
    }
  }

  // プロンプト収集
  const rawPrompts: string[] = [];
  if (options.prompt && options.prompt.length > 0) {
    rawPrompts.push(...options.prompt);
  }
  if (rawPrompts.length === 0 && options.positionals.length > 0) {
    rawPrompts.push(options.positionals.join(' '));
  }

  if (rawPrompts.length === 0) {
    // 標準入力から取得
    if (process.stdin.isTTY) {
      console.error(
        'エラー: プロンプトが指定されていません。\n--prompt を指定するか、標準入力から渡してください。'
      );
      process.exit(1);
    }
    const stdinContent = (await readAllStdin()).trim();
    if (!stdinContent) {
      console.error('エラー: 標準入力から読み込んだプロンプトが空です。');
      process.exit(1);
    }
    rawPrompts.push(stdinContent);
  }

  // 空文字プロンプトのチェック
  if (rawPrompts.some((p) => p.trim() === '')) {
    console.error('エラー: プロンプトが空です。');
    process.exit(1);
  }

  // 複数プロンプト時は --parallel 必須
  if (rawPrompts.length > 1 && !options.parallel) {
    console.error('エラー: 複数のプロンプトを渡す場合は --parallel を指定してください');
    process.exit(1);
  }

  const cwd = process.cwd();
  const fullContentNames = parseFullContentNames(options['full-content-names']);
  const traceTool = options['trace-tool'] || 'aim2-cli';

  if (options.parallel) {
    // ==========================================
    // 並列実行パス
    // ==========================================
    const entries: ResultEntry[] = [];
    const targets: ParallelTarget[] = [];

    for (let i = 0; i < rawPrompts.length; i++) {
      const original = rawPrompts[i];
      const expandedResult = tryExpandPrompt(original, cwd, fullContentNames);

      if (rawPrompts.length === 1 && expandedResult.refs.length >= 2) {
        console.error(
          '注意: --parallel でプロンプトが1件です。複数ジョブにするには --prompt を複数渡してください。 例: aim2 --parallel --prompt "@a.py 要約して" "@b.py 要約して"'
        );
      }

      const firstRef = expandedResult.refs[0];
      entries.push(
        makeEntry({
          index: i + 1,
          prompt: original,
          rawPath: firstRef ? firstRef.rawPath : '',
          resolvedPath: firstRef ? firstRef.resolved : '',
          success: false,
          error: expandedResult.error,
        })
      );

      if (expandedResult.error === null && expandedResult.expanded !== null) {
        targets.push({
          index: i,
          expandedPrompt: expandedResult.expanded,
        });
      }
    }

    for (const target of targets) {
      const resolvedSession = resolveSessionId();
      target.sessionId = resolvedSession.sessionId;
      printSessionId(resolvedSession.sessionId, `session_id[${target.index + 1}]`);
    }

    await runParallel({
      provider: resolved.spec.provider,
      modelId: resolved.spec.id,
      modelAlias: resolved.alias,
      jobs: options.jobs ?? JOBS_DEFAULT,
      entries,
      targets,
      traceTool,
    });

    const output = formatResults(entries, {
      format: options.format,
      parallel: true,
    });
    console.log(output);
  } else {
    // ==========================================
    // 単発実行パス
    // ==========================================
    const original = rawPrompts[0];
    const expandedResult = tryExpandPrompt(original, cwd, fullContentNames);

    if (expandedResult.error !== null || expandedResult.expanded === null) {
      console.error(`エラー: ${expandedResult.error || 'プロンプトの展開に失敗しました'}`);
      process.exit(1);
    }

    const isTTY = Boolean(process.stdout.isTTY);
    const shouldStream = isTTY && !options.format;
    const resolvedSession = resolveSessionId(options['session-id'] ?? options['thread-id']);
    const history = loadSessionHistory(resolvedSession.sessionId);
    const promptInput = buildPromptInput(history, expandedResult.expanded);
    printSessionId(resolvedSession.sessionId);

    try {
      const trace = resolveTrace({
        tool: traceTool,
        prompt_index: '1',
        ...(expandedResult.refs[0] ? { file_path: expandedResult.refs[0].rawPath } : {}),
      });

      const result = await runPrompt(
        resolved.spec.provider,
        resolved.spec.id,
        promptInput,
        {
          stream: shouldStream,
        }
      );

      const trimmed = result.text.trim();
      if (!trimmed) {
        throw new AimError('モデルからの応答が空でした。', {
          code: 'EMPTY_RESPONSE',
          provider: resolved.spec.provider,
        });
      }

      // トレースログを記録
      try {
        appendLog(
          buildLogRecord({
            model: resolved.alias,
            provider: resolved.spec.provider,
            prompt: expandedResult.expanded,
            response: trimmed,
            usage: result.usage,
            sessionId: resolvedSession.sessionId,
            trace,
          })
        );
      } catch (logErr) {
        console.error(`警告: ログの追記に失敗しました: ${logErr}`);
      }

      const firstRef = expandedResult.refs[0];
      const entry = makeEntry({
        index: 1,
        prompt: original,
        rawPath: firstRef ? firstRef.rawPath : '',
        resolvedPath: firstRef ? firstRef.resolved : '',
        success: true,
        response: trimmed,
      });

      if (!options.format) {
        if (!shouldStream) {
          console.log(trimmed);
        } else if (!trimmed.endsWith('\n')) {
          console.log();
        }
      } else {
        const output = formatResults([entry], {
          format: options.format,
          parallel: false,
        });
        console.log(output);
      }
    } catch (err) {
      const normalized = normalizeError(err, resolved.spec.provider);
      console.error(`エラー: ${normalized.formatUserMessage()}`);
      process.exit(1);
    }
  }
}

// CLI 直接実行判定
if (process.argv[1] && (process.argv[1].endsWith('cli.ts') || process.argv[1].endsWith('cli.js'))) {
  main().catch((err) => {
    if (
      err instanceof ConfigError ||
      err instanceof AtError ||
      err instanceof RunnerError ||
      err instanceof AimError ||
      err instanceof PricingError
    ) {
      console.error(err.message);
    } else {
      console.error(err instanceof Error ? err.message : String(err));
    }
    process.exit(1);
  });
}
