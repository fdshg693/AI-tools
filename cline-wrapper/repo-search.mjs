import { resolve } from "node:path"
import { z } from "zod"
import { runAgent } from "./lib/agent-runner.mjs"
import { createCompletingTool } from "./lib/completing-tool.mjs"
import { DEFAULT_MODEL_ID, resolveModel } from "./lib/config.mjs"
import { ENV_PATH, loadDotenv, missingRequiredKeyMessage } from "./lib/dotenv.mjs"
import { makeRepoTools } from "./lib/repo-tools.mjs"

// ---------------------------------------------------------------------------
// .env loader (no external dependency). Real environment variables win.
// ---------------------------------------------------------------------------

loadDotenv(ENV_PATH)

// ---------------------------------------------------------------------------
// CLI parsing
// ---------------------------------------------------------------------------

const args = process.argv.slice(2)
let repoRoot = process.cwd()
let question = ""
let modelArg = null
for (let i = 0; i < args.length; i++) {
  const a = args[i]
  if (a === "--repo" || a === "-r") {
    repoRoot = resolve(args[++i] ?? ".")
  } else if (a === "--model" || a === "-m") {
    modelArg = args[++i] ?? null
  } else if (a === "-h" || a === "--help") {
    process.stdout.write(
      "Usage: node repo-search.mjs [--repo <path>] [--model <id>] <question>\n" +
        "  --repo / -r   Repository root to search (default: cwd)\n" +
        "  --model / -m  Model id (default: " +
        DEFAULT_MODEL_ID +
        "; short name ok, e.g. minimax-m3)\n" +
        "Reads CLINE_API_KEY from tools/cline-wrapper/.env.\n",
    )
    process.exit(0)
  } else {
    question = (question + " " + a).trim()
  }
}
question = question.trim()
if (!question) {
  console.error('Question is required: node repo-search.mjs "your question"')
  process.exit(1)
}
repoRoot = resolve(repoRoot)

const { providerId, modelId } = resolveModel(modelArg)

const apiKey = process.env.CLINE_API_KEY
if (!apiKey) {
  console.error(missingRequiredKeyMessage("CLINE_API_KEY", ENV_PATH))
  process.exit(1)
}

// ---------------------------------------------------------------------------
// Stage 1: Explorer agent
// ---------------------------------------------------------------------------

const explorerSystemPrompt = [
  "あなたはコードリポジトリの探索エージェントです。与えられた質問に答えるために役立ちそうなファイルを網羅的に探索し、関連ファイルと有効だったGrepキーワードを確定することがあなたの仕事です。",
  "",
  "利用可能なツール:",
  "- grep_search: リポジトリを正規表現で検索し、マッチしたファイル・行番号・プレビューを返す。複数のキーワード・複数のアプローチを試すこと。",
  "- read_file: 指定ファイルの内容を行番号付きで返す。候補ファイルの関連度を判断するために必要な範囲だけ読む。",
  "- list_files: ディレクトリ配下のファイル一覧を返す。見当をつける前に全体像を掴むのに使う。",
  "",
  "探索の方針:",
  "1. まず list_files や grep_search で見当をつけ、関連しそうなファイルを広く見つける。",
  "2. 候補ファイルを read_file で部分的に読み、関連度を判断する。",
  "3. 抜け漏れを減らすため、異なるキーワード・異なる検索アプローチを複数試す。",
  "",
  "出力の制約（重要）:",
  "- 生のファイル内容を出力テキストに貼らないこと。パスと関連度・理由のみを扱う。",
  "- 探索が終わったら、必ず最後に submit_findings ツールを1回だけ呼び出して結果を確定すること。それがこの実行の完了を意味する。",
  "- submit_findings には以下のみを含める:",
  "  - relevantFiles: 関連ファイルのリスト。各要素は { path(リポジトリルートからの相対パス), importance(high/medium/low), reason(簡潔な理由) }",
  "  - grepKeywords: 探索で有効だったGrepキーワード・正規表現の文字列配列",
  "  - overview: 現時点で見えてきた概要。どのようなファイルがどの責務を担い、どれが重要かという傾向を、詳細に立ち入らず概要レベルで述べる。",
].join("\n")

function makeExplorerTools(repoTools) {
  const { tool: submitFindings, getResult: getFindings } = createCompletingTool({
    name: "submit_findings",
    description:
      "Submit the exploration findings and end the run. Call this exactly once when exploration is complete. " +
      "Do NOT include raw file contents; include only paths, importance, reasons, effective grep keywords, and a brief overview.",
    inputSchema: z.object({
      relevantFiles: z
        .array(
          z.object({
            path: z.string().describe("File path relative to repo root (POSIX separators)."),
            importance: z.enum(["high", "medium", "low"]),
            reason: z.string().describe("Brief reason this file is relevant."),
          }),
        )
        .describe("Relevant files found during exploration."),
      grepKeywords: z.array(z.string()).describe("Grep keywords/regex patterns that were effective."),
      overview: z.string().describe("Brief overview of what was found and relative importance."),
    }),
    formatResult: (input) => ({ ok: true, received: `${input.relevantFiles.length} files` }),
  })
  return {
    tools: [repoTools.grepSearch, repoTools.readFile, repoTools.listFiles, submitFindings],
    getFindings,
  }
}


// ---------------------------------------------------------------------------
// Stage 2: Answerer agent
// ---------------------------------------------------------------------------

const answererSystemPrompt = [
  "あなたはコードリポジトリの回答エージェントです。先行の探索エージェントが確定した関連ファイル情報をもとに、ファイルを実際に読み込み、根拠のある正確な回答を作成することがあなたの仕事です。",
  "",
  "利用可能なツール:",
  "- grep_search: リポジトリを正規表現で検索し、追加確認に使う。",
  "- read_file: 指定ファイルの内容を行番号付きで取得する。",
  "",
  "回答の方針:",
  "1. 渡された関連ファイルリストのうち、重要度が高いものから read_file で読む。",
  "2. 必要に応じて grep_search で追加確認する。",
  "3. 回答には正確なファイルパス・行番号を根拠として含める。推測で書かない。",
  "4. 読み取った内容だけを根拠にする。見つからなかった点があれば正直に書く。",
  "5. 回答がまとまったら、必ず最後に submit_answer ツールを1回だけ呼び出して最終回答を確定すること。それがこの実行の完了を意味する。",
].join("\n")

function makeAnswererTools(repoTools) {
  const { tool: submitAnswer, getResult: getAnswer } = createCompletingTool({
    name: "submit_answer",
    description:
      "Submit the final grounded answer and end the run. Call this exactly once when the answer is ready.",
    inputSchema: z.object({
      answer: z
        .string()
        .describe("The final answer, grounded in files actually read, citing paths and line numbers."),
      citations: z
        .array(
          z.object({
            path: z.string(),
            lines: z.string().describe("Line range or specific lines, e.g. '12-18'."),
            note: z.string().describe("What this part of the file supports."),
          }),
        )
        .describe("Citations backing the answer."),
    }),
  })
  return {
    tools: [repoTools.grepSearch, repoTools.readFile, submitAnswer],
    getAnswer,
  }
}


// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

function fmtUsage(u) {
  if (!u) return ""
  return `in=${u.inputTokens ?? 0} out=${u.outputTokens ?? 0} cost=${u.totalCost ?? 0}`
}

console.error(`[repo-search] repo=${repoRoot}`)
console.error(`[repo-search] model=${modelId}`)
console.error(`[repo-search] question=${question}`)

const repoTools = makeRepoTools(repoRoot)

// --- Stage 1 ---
const explorer = makeExplorerTools(repoTools)
const r1 = await runAgent({
  apiKey,
  providerId,
  modelId,
  systemPrompt: explorerSystemPrompt,
  tools: explorer.tools,
  prompt: `質問: ${question}\nリポジトリルート: ${repoRoot}\n探索を開始し、最後に submit_findings を呼び出して結果を確定してください。`,
  maxIterations: 14,
  label: "explorer",
})
if (r1.status !== "completed") {
  console.error(`\n[explorer] run ${r1.status}: ${r1.error?.message ?? ""}`)
}
let findings = explorer.getFindings()
if (!findings) {
  console.error("[explorer] submit_findings was not called; falling back to output text.")
  findings = {
    relevantFiles: [],
    grepKeywords: [],
    overview: r1.outputText ?? "(no output)",
  }
}
console.error(`\n[explorer] done iterations=${r1.iterations} ${fmtUsage(r1.usage)}`)

const findingsJson = JSON.stringify(findings, null, 2)
console.error(`[explorer] findings files=${findings.relevantFiles.length}`)

// --- Stage 2 ---
const answerer = makeAnswererTools(repoTools)
const r2 = await runAgent({
  apiKey,
  providerId,
  modelId,
  systemPrompt: answererSystemPrompt,
  tools: answerer.tools,
  prompt:
    `質問: ${question}\n` +
    `リポジトリルート: ${repoRoot}\n\n` +
    `先行の探索エージェントが確定した関連ファイル情報（JSON）:\n${findingsJson}\n\n` +
    `この情報をもとに、重要度の高いファイルから read_file で読み、根拠のある回答を作成し、最後に submit_answer を呼び出して確定してください。`,
  maxIterations: 10,
  label: "answerer",
})
if (r2.status !== "completed") {
  console.error(`\n[answerer] run ${r2.status}: ${r2.error?.message ?? ""}`)
}
const answer = answerer.getAnswer()
console.error(`\n[answerer] done iterations=${r2.iterations} ${fmtUsage(r2.usage)}`)

console.error("=".repeat(60))
if (answer) {
  process.stdout.write(answer.answer + "\n")
  if (answer.citations?.length) {
    process.stdout.write("\n--- 根拠 ---\n")
    for (const c of answer.citations) {
      process.stdout.write(`- ${c.path}:${c.lines} — ${c.note}\n`)
    }
  }
} else {
  process.stdout.write((r2.outputText ?? "(no answer produced)") + "\n")
}
