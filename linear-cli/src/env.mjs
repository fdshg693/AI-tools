import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const SCRIPT_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = path.resolve(SCRIPT_DIRECTORY, "..");
export const DEFAULT_ENV_PATH = path.join(PACKAGE_ROOT, ".env");

export function readPackageVersion() {
  const raw = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, "package.json"), "utf8"));
  const version = String(raw.version ?? "").trim();
  if (!version) {
    throw new Error(`package.json の version が見つかりません: ${PACKAGE_ROOT}`);
  }
  return version;
}

export function missingRequiredKeyMessage(key, envPath = DEFAULT_ENV_PATH) {
  const envState = key in process.env ? "空で設定されている" : "未設定";
  let fileState;
  try {
    fileState = fs.statSync(envPath).isFile()
      ? `${envPath} はありますが、${key} が無いか空です。`
      : `想定した .env は ${envPath} ですが、ファイルがありません。`;
  } catch {
    fileState = `想定した .env は ${envPath} ですが、ファイルがありません。`;
  }
  return `${key} が解決できません。\n環境変数 ${key} は${envState}です。\n${fileState}`;
}

/** tools/linear-cli/.env を読み込む。実行時のカレントディレクトリに依存しない。 */
export function loadLocalEnv(envPath = DEFAULT_ENV_PATH) {
  try {
    process.loadEnvFile(envPath);
  } catch {
    // .env が無くても LINEAR_API_KEY が環境変数で設定済みなら問題ない。
  }
}
