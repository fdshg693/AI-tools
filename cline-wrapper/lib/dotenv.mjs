import { readFileSync, statSync } from "node:fs"
import { resolve } from "node:path"
import { fileURLToPath } from "node:url"

export const ENV_PATH = resolve(fileURLToPath(new URL(".", import.meta.url)), "..", ".env")

/** Minimal .env loader (no external dependency). Real environment variables win. */
export function loadDotenv(envPath = ENV_PATH) {
  let text
  try {
    text = readFileSync(envPath, "utf-8")
  } catch {
    return
  }
  for (const raw of text.split(/\r?\n/)) {
    let line = raw.trim()
    if (!line || line.startsWith("#")) continue
    if (line.startsWith("export ")) line = line.slice(7).trim()
    const eq = line.indexOf("=")
    if (eq === -1) continue
    const key = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()
    if (value.length >= 2 && value[0] === value[value.length - 1] && "\"'".includes(value[0])) {
      value = value.slice(1, -1)
    }
    if (key && !(key in process.env)) process.env[key] = value
  }
}

export function missingRequiredKeyMessage(key, envPath = ENV_PATH) {
  const envState = key in process.env ? "空で設定されている" : "未設定"
  let fileState
  try {
    fileState = statSync(envPath).isFile()
      ? `${envPath} はありますが、${key} が無いか空です。`
      : `想定した .env は ${envPath} ですが、ファイルがありません。`
  } catch {
    fileState = `想定した .env は ${envPath} ですが、ファイルがありません。`
  }
  return `${key} が解決できません。\n環境変数 ${key} は${envState}です。\n${fileState}`
}
