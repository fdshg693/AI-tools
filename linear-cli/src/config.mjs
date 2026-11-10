import { existsSync, readFileSync } from "node:fs";
import { dirname, join, parse } from "node:path";
import process from "node:process";

const CONFIG_DIR_NAME = ".linear-cli";
const CONFIG_FILE_NAME = "config.json";

/** `start` から親方向に `.linear-cli/config.json` を探索する。見つからなければ null。 */
export function findConfigPath(start) {
  let current = start;
  const root = parse(current).root;
  for (;;) {
    const candidate = join(current, CONFIG_DIR_NAME, CONFIG_FILE_NAME);
    if (existsSync(candidate)) return candidate;
    if (current === root) return null;
    current = dirname(current);
  }
}

function validateOptionalString(raw, configPath, field) {
  if (raw === undefined) return undefined;
  if (typeof raw !== "string" || raw.trim() === "") {
    throw new Error(`${configPath}: ${field} は空でない文字列で指定してください。`);
  }
  return raw;
}

/**
 * `.linear-cli/config.json` の team/project 既定値を読み込む。
 * 設定ファイルが見つからない場合は空オブジェクト（team/project絞り込み無し）を返す。
 */
export function loadConfig(start = process.cwd()) {
  const configPath = findConfigPath(start);
  if (!configPath) return {};

  let raw;
  try {
    raw = JSON.parse(readFileSync(configPath, "utf8"));
  } catch (error) {
    throw new Error(`${configPath} のJSON構文が不正です: ${error.message}`);
  }

  return {
    team: validateOptionalString(raw.team, configPath, "team"),
    project: validateOptionalString(raw.project, configPath, "project"),
  };
}
