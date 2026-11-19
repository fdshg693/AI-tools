export type AimErrorCode =
  | 'AUTHENTICATION_ERROR'
  | 'RATE_LIMIT_ERROR'
  | 'INVALID_MODEL'
  | 'CONTEXT_LENGTH_EXCEEDED'
  | 'NETWORK_ERROR'
  | 'PROVIDER_ERROR'
  | 'EMPTY_RESPONSE'
  | 'CONFIG_ERROR'
  | 'UNKNOWN_ERROR';

export interface AimErrorOptions {
  code?: AimErrorCode;
  provider?: string;
  statusCode?: number;
  cause?: unknown;
}

/**
 * aim2 共通のエラークラス
 */
export class AimError extends Error {
  readonly code: AimErrorCode;
  readonly provider?: string;
  readonly statusCode?: number;
  readonly originalError?: unknown;

  constructor(message: string, options: AimErrorOptions = {}) {
    super(message);
    this.name = 'AimError';
    this.code = options.code ?? 'UNKNOWN_ERROR';
    this.provider = options.provider;
    this.statusCode = options.statusCode;
    this.originalError = options.cause;
    if (options.cause instanceof Error && !this.cause) {
      this.cause = options.cause;
    }
  }

  /**
   * ユーザー向け表示用のフォーマット文字列
   */
  formatUserMessage(): string {
    const prov = this.provider ? `[${this.provider}] ` : '';
    return `${prov}${this.message}`;
  }
}

/**
 * 各種例外（Vercel AI SDK, 各プロバイダ SDK, ネットワーク例外等）を AimError に正規化する
 */
export function normalizeError(err: unknown, provider?: string): AimError {
  if (err instanceof AimError) {
    if (provider && !err.provider) {
      return new AimError(err.message, {
        code: err.code,
        provider,
        statusCode: err.statusCode,
        cause: err.cause,
      });
    }
    return err;
  }

  // 内部原因（cause）があれば再帰的に深掘り
  const targetErr = (err && typeof err === 'object' && 'cause' in err && err.cause instanceof Error)
    ? (err as { cause: Error }).cause
    : err;

  const rawMessage = targetErr instanceof Error ? targetErr.message : String(targetErr ?? 'Unknown error');
  const errObj = (targetErr && typeof targetErr === 'object') ? (targetErr as Record<string, unknown>) : {};

  // HTTP ステータスコードの抽出
  let statusCode: number | undefined = undefined;
  if (typeof errObj.statusCode === 'number') {
    statusCode = errObj.statusCode;
  } else if (typeof errObj.status === 'number') {
    statusCode = errObj.status;
  }

  const codeStr = typeof errObj.code === 'string' ? errObj.code : '';
  const nameStr = typeof errObj.name === 'string' ? errObj.name : '';
  const lowerMsg = rawMessage.toLowerCase();

  let code: AimErrorCode = 'UNKNOWN_ERROR';
  let userMessage = rawMessage;

  // 判定ロジック
  if (
    statusCode === 401 ||
    statusCode === 403 ||
    lowerMsg.includes('unauthorized') ||
    lowerMsg.includes('api key') ||
    lowerMsg.includes('apikey') ||
    lowerMsg.includes('invalid_api_key') ||
    lowerMsg.includes('authentication') ||
    nameStr === 'LoadAPIKeyError'
  ) {
    code = 'AUTHENTICATION_ERROR';
    userMessage = `認証エラー: APIキーが無効であるか設定されていません (${rawMessage})`;
  } else if (
    statusCode === 429 ||
    lowerMsg.includes('rate limit') ||
    lowerMsg.includes('rate_limit') ||
    lowerMsg.includes('too many requests') ||
    lowerMsg.includes('quota') ||
    lowerMsg.includes('exceeded your current quota')
  ) {
    code = 'RATE_LIMIT_ERROR';
    userMessage = `レート制限エラー: リクエスト上限またはクォータを超過しました (${rawMessage})`;
  } else if (
    statusCode === 404 ||
    lowerMsg.includes('model not found') ||
    lowerMsg.includes('does not exist') ||
    lowerMsg.includes('not found') ||
    lowerMsg.includes('no such model') ||
    nameStr === 'NoSuchModelError'
  ) {
    code = 'INVALID_MODEL';
    userMessage = `モデルエラー: 指定されたモデルが存在しないかアクセス権がありません (${rawMessage})`;
  } else if (
    lowerMsg.includes('context length') ||
    lowerMsg.includes('context_length') ||
    lowerMsg.includes('maximum context length') ||
    lowerMsg.includes('prompt is too long') ||
    lowerMsg.includes('tokens exceeds')
  ) {
    code = 'CONTEXT_LENGTH_EXCEEDED';
    userMessage = `コンテキスト長超過: プロンプトがモデルの上限トークン数を超えています (${rawMessage})`;
  } else if (
    codeStr === 'ECONNREFUSED' ||
    codeStr === 'ETIMEDOUT' ||
    codeStr === 'ENOTFOUND' ||
    nameStr === 'AbortError' ||
    lowerMsg.includes('fetch failed') ||
    lowerMsg.includes('network') ||
    lowerMsg.includes('econnrefused') ||
    lowerMsg.includes('timeout')
  ) {
    code = 'NETWORK_ERROR';
    userMessage = `ネットワークエラー: プロバイダへの通信に失敗しました (${rawMessage})`;
  } else if (
    (statusCode !== undefined && statusCode >= 500) ||
    lowerMsg.includes('internal server error') ||
    lowerMsg.includes('service unavailable') ||
    lowerMsg.includes('overloaded')
  ) {
    code = 'PROVIDER_ERROR';
    userMessage = `プロバイダサーバーエラー: プロバイダ側で一時的な障害が発生しています (${rawMessage})`;
  } else if (lowerMsg.includes('empty response') || lowerMsg.includes('応答が空')) {
    code = 'EMPTY_RESPONSE';
    userMessage = 'モデルからの応答が空でした。';
  }

  return new AimError(userMessage, {
    code,
    provider,
    statusCode,
    cause: err,
  });
}
