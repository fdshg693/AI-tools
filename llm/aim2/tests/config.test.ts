import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import process from 'node:process';
import {
  loadDotenv,
  missingRequiredKeyMessage,
  resolveApiKey,
  validateModelsConfig,
  resolveModel,
  ConfigError,
} from '../src/config.js';

describe('config', () => {
  let tmpDir: string;
  const originalEnv = { ...process.env };

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aim2-test-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    // 環境変数を元に戻す
    for (const key of Object.keys(process.env)) {
      if (!(key in originalEnv)) {
        delete process.env[key];
      }
    }
    for (const [key, value] of Object.entries(originalEnv)) {
      process.env[key] = value;
    }
  });

  describe('missingRequiredKeyMessage', () => {
    it('ファイルが存在しない場合の診断メッセージを正しく生成する', () => {
      delete process.env.TEST_API_KEY;
      const nonExistentPath = path.join(tmpDir, '.env');
      const msg = missingRequiredKeyMessage('TEST_API_KEY', nonExistentPath);

      assert.match(msg, /TEST_API_KEY が解決できません。/);
      assert.match(msg, /環境変数 TEST_API_KEY は未設定です。/);
      assert.match(msg, new RegExp(`想定した \\.env は ${path.normalize(nonExistentPath).replace(/\\/g, '\\\\')} ですが、ファイルがありません。`));
    });

    it('環境変数が空で設定されている場合の診断メッセージ', () => {
      process.env.TEST_API_KEY = '';
      const nonExistentPath = path.join(tmpDir, '.env');
      const msg = missingRequiredKeyMessage('TEST_API_KEY', nonExistentPath);

      assert.match(msg, /TEST_API_KEY が解決できません。/);
      assert.match(msg, /環境変数 TEST_API_KEY は空で設定されているです。/);
    });

    it('ファイルは存在するがキーが無い場合の診断メッセージ', () => {
      delete process.env.TEST_API_KEY;
      const envPath = path.join(tmpDir, '.env');
      fs.writeFileSync(envPath, 'OTHER_KEY=123\n');
      const msg = missingRequiredKeyMessage('TEST_API_KEY', envPath);

      assert.match(msg, /TEST_API_KEY が解決できません。/);
      assert.match(msg, /環境変数 TEST_API_KEY は未設定です。/);
      assert.match(msg, new RegExp(`${path.normalize(envPath).replace(/\\/g, '\\\\')} はありますが、TEST_API_KEY が無いか空です。`));
    });
  });

  describe('loadDotenv', () => {
    it('.env から環境変数をロードする', () => {
      delete process.env.AIM2_TEST_KEY_1;
      delete process.env.AIM2_TEST_KEY_2;
      delete process.env.AIM2_TEST_KEY_3;

      const envPath = path.join(tmpDir, '.env');
      fs.writeFileSync(
        envPath,
        `
# コメント行
AIM2_TEST_KEY_1=value1
export AIM2_TEST_KEY_2="value 2"
AIM2_TEST_KEY_3='value 3'
`
      );

      loadDotenv(envPath);

      assert.equal(process.env.AIM2_TEST_KEY_1, 'value1');
      assert.equal(process.env.AIM2_TEST_KEY_2, 'value 2');
      assert.equal(process.env.AIM2_TEST_KEY_3, 'value 3');
    });

    it('既存のプロセス環境変数を上書きしない（プロセス優先）', () => {
      process.env.AIM2_EXISTING_KEY = 'from_process';

      const envPath = path.join(tmpDir, '.env');
      fs.writeFileSync(envPath, 'AIM2_EXISTING_KEY=from_env_file\n');

      loadDotenv(envPath);

      assert.equal(process.env.AIM2_EXISTING_KEY, 'from_process');
    });

    it('空文字のプロセス環境変数も上書きしない', () => {
      process.env.AIM2_EMPTY_KEY = '';

      const envPath = path.join(tmpDir, '.env');
      fs.writeFileSync(envPath, 'AIM2_EMPTY_KEY=from_env_file\n');

      loadDotenv(envPath);

      assert.equal(process.env.AIM2_EMPTY_KEY, '');
    });
  });

  describe('resolveApiKey', () => {
    it('利用プロバイダのキーが設定されている場合は解決する', () => {
      process.env.OPENAI_API_KEY = 'sk-openai-test';
      const auth = resolveApiKey('openai');
      assert.equal(auth.apiKey, 'sk-openai-test');
    });

    it('利用プロバイダのキーが未設定の場合は ConfigError をスローする', () => {
      delete process.env.ANTHROPIC_API_KEY;
      assert.throws(
        () => resolveApiKey('anthropic', path.join(tmpDir, '.env')),
        (err: unknown) => {
          assert(err instanceof ConfigError);
          assert.match(err.message, /ANTHROPIC_API_KEY が解決できません。/);
          return true;
        }
      );
    });

    it('OpenAI 利用時に Anthropic キーが未設定でもエラーにならない', () => {
      process.env.OPENAI_API_KEY = 'sk-openai-test';
      delete process.env.ANTHROPIC_API_KEY;
      const auth = resolveApiKey('openai');
      assert.equal(auth.apiKey, 'sk-openai-test');
    });

    it('Ollama は API キー未設定でも動作する', () => {
      delete process.env.OPENAI_API_KEY;
      const auth = resolveApiKey('ollama');
      assert.equal(auth.baseURL, 'http://127.0.0.1:11434/v1');
    });
  });

  describe('validateModelsConfig', () => {
    const validConfig = {
      default: 'model-a',
      models: {
        'model-a': {
          enable: true,
          provider: 'openrouter',
          id: 'z-ai/glm-5.3-flash',
          description: 'Model A desc',
        },
        'model-b': {
          enable: true,
          provider: 'openai',
          id: 'gpt-4o',
          description: 'Model B desc',
        },
      },
    };

    it('正常な設定をバリデーションできる', () => {
      const parsed = validateModelsConfig(validConfig);
      assert.equal(parsed.default, 'model-a');
      assert.equal(parsed.models['model-a'].provider, 'openrouter');
      assert.equal(parsed.models['model-b'].id, 'gpt-4o');
    });

    it('provider が欠落しているモデル定義は拒絶する', () => {
      const invalid = {
        default: 'model-a',
        models: {
          'model-a': {
            enable: true,
            // provider 欠落
            id: 'foo/bar',
            description: 'desc',
          },
        },
      };

      assert.throws(
        () => validateModelsConfig(invalid),
        (err: unknown) => {
          assert(err instanceof ConfigError);
          assert.match(err.message, /provider が空でない文字列ではありません/);
          return true;
        }
      );
    });

    it('default が models に存在しない場合は拒絶する', () => {
      const invalid = {
        ...validConfig,
        default: 'non-existent',
      };

      assert.throws(
        () => validateModelsConfig(invalid),
        (err: unknown) => {
          assert(err instanceof ConfigError);
          assert.match(err.message, /default 'non-existent' は models の略記に含まれていません/);
          return true;
        }
      );
    });

    it('default が enable: false の場合は拒絶する', () => {
      const invalid = {
        default: 'model-a',
        models: {
          'model-a': {
            enable: false,
            provider: 'openai',
            id: 'gpt-4o',
            description: 'Disabled default',
          },
        },
      };

      assert.throws(
        () => validateModelsConfig(invalid),
        (err: unknown) => {
          assert(err instanceof ConfigError);
          assert.match(err.message, /default 'model-a' は enable: false に設定されています/);
          return true;
        }
      );
    });
  });

  describe('resolveModel', () => {
    const config = validateModelsConfig({
      default: 'default-alias',
      models: {
        'default-alias': {
          enable: true,
          provider: 'openrouter',
          id: 'z-ai/glm-5.3-flash',
          description: 'Default model',
        },
        'other-alias': {
          enable: true,
          provider: 'openai',
          id: 'gpt-4o',
          description: 'Other model',
        },
        'disabled-alias': {
          enable: false,
          provider: 'anthropic',
          id: 'claude-3-5',
          description: 'Disabled model',
        },
      },
    });

    it('未指定時はデフォルトモデルを解決する', () => {
      const resolved = resolveModel(config);
      assert.equal(resolved.alias, 'default-alias');
      assert.equal(resolved.spec.id, 'z-ai/glm-5.3-flash');
      assert.equal(resolved.spec.provider, 'openrouter');
    });

    it('指定された略記を解決する', () => {
      const resolved = resolveModel(config, 'other-alias');
      assert.equal(resolved.alias, 'other-alias');
      assert.equal(resolved.spec.id, 'gpt-4o');
      assert.equal(resolved.spec.provider, 'openai');
    });

    it('無効化されたモデルは解決時にエラーとなる', () => {
      assert.throws(
        () => resolveModel(config, 'disabled-alias'),
        (err: unknown) => {
          assert(err instanceof ConfigError);
          assert.match(err.message, /無効化 \(enable: false\) されています/);
          return true;
        }
      );
    });

    it('未知のモデル略記は解決時にエラーとなる', () => {
      assert.throws(
        () => resolveModel(config, 'unknown-model'),
        (err: unknown) => {
          assert(err instanceof ConfigError);
          assert.match(err.message, /未知のモデル略記です: 'unknown-model'/);
          return true;
        }
      );
    });
  });
});
