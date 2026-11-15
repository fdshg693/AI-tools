import { generateText, streamText, type LanguageModel, type ModelMessage } from 'ai';
import process from 'node:process';
import { defaultRegistry, ProviderRegistry } from './providers/registry.js';
import type { ProviderContext } from './providers/types.js';

export class RunnerError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'RunnerError';
  }
}

export interface RunOptions {
  model: LanguageModel;
  prompt: string | Array<ModelMessage>;
  stream?: boolean;
  onChunk?: (chunk: string) => void;
}

export interface RunResult {
  text: string;
  usage?: {
    promptTokens?: number;
    completionTokens?: number;
    totalTokens?: number;
  };
  finishReason?: string;
}

/**
 * プロバイダとモデルIDから LanguageModel を解決し、プロンプトを実行する高水準ランナー
 */
export async function runPrompt(
  provider: string,
  modelId: string,
  prompt: string | Array<ModelMessage>,
  options: {
    stream?: boolean;
    context?: ProviderContext;
    registry?: ProviderRegistry;
    onChunk?: (chunk: string) => void;
  } = {}
): Promise<RunResult> {
  const registry = options.registry || defaultRegistry;
  let model: LanguageModel;
  try {
    model = await registry.resolveLanguageModel(provider, modelId, options.context);
  } catch (err) {
    throw new RunnerError(
      `モデル '${provider}:${modelId}' の初期化に失敗しました: ${err instanceof Error ? err.message : String(err)}`,
      err
    );
  }

  return executeModel({
    model,
    prompt,
    stream: options.stream,
    onChunk: options.onChunk,
  });
}

/**
 * 与えられた LanguageModel を用いてプロンプトを実行する。
 * stream が true の場合はストリーミング出力し、false の場合は一括取得する。
 */
export async function executeModel(options: RunOptions): Promise<RunResult> {
  const stream = options.stream ?? Boolean(process.stdout.isTTY);

  try {
    if (stream) {
      const result = streamText({
        model: options.model,
        prompt: options.prompt,
      });

      for await (const chunk of result.textStream) {
        if (options.onChunk) {
          options.onChunk(chunk);
        } else {
          process.stdout.write(chunk);
        }
      }

      const text = await result.text;
      const usageRaw = await result.usage;
      const finishReason = await result.finishReason;

      return {
        text,
        usage: usageRaw
          ? {
              promptTokens: usageRaw.inputTokens,
              completionTokens: usageRaw.outputTokens,
              totalTokens: usageRaw.totalTokens,
            }
          : undefined,
        finishReason,
      };
    } else {
      const result = await generateText({
        model: options.model,
        prompt: options.prompt,
      });

      return {
        text: result.text,
        usage: result.usage
          ? {
              promptTokens: result.usage.inputTokens,
              completionTokens: result.usage.outputTokens,
              totalTokens: result.usage.totalTokens,
            }
          : undefined,
        finishReason: result.finishReason,
      };
    }
  } catch (err) {
    throw new RunnerError(
      `AI モデルの呼び出しに失敗しました: ${err instanceof Error ? err.message : String(err)}`,
      err
    );
  }
}
