import { createTool } from "@cline/sdk"
import { z } from "zod"
import { runAgent } from "./lib/agent-runner.mjs"
import { resolveModel } from "./lib/config.mjs"
import { ENV_PATH, loadDotenv, missingRequiredKeyMessage } from "./lib/dotenv.mjs"

loadDotenv(ENV_PATH)

const apiKey = process.env.CLINE_API_KEY
const isSelfTest = process.argv.includes("--self-test")
if (!isSelfTest && !apiKey) {
  console.error(missingRequiredKeyMessage("CLINE_API_KEY", ENV_PATH))
  process.exit(1)
}

const args = process.argv.slice(2).filter((a) => a !== "--self-test")
let modelArg = null
const promptParts = []
for (let i = 0; i < args.length; i++) {
  const a = args[i]
  if (a === "--model" || a === "-m") {
    modelArg = args[++i] ?? null
  } else {
    promptParts.push(a)
  }
}

const prompt =
  promptParts.join(" ") ||
  "Call the record_custom_tool_call tool with the message 'Cline custom tool is working', then briefly report its result."

const { providerId, modelId } = resolveModel(modelArg)

let customToolCallCount = 0

const recordCustomToolCall = createTool({
  name: "record_custom_tool_call",
  description:
    "Record a short verification message and return a structured confirmation. Use this tool when the user asks you to verify that the custom tool works. This tool is read-only and has no external side effects.",
  inputSchema: z.object({
    message: z
      .string()
      .min(1)
      .max(200)
      .describe("The short message to record for this verification."),
  }),
  async execute(input) {
    customToolCallCount += 1
    return {
      ok: true,
      message: input.message,
      callNumber: customToolCallCount,
      calledAt: new Date().toISOString(),
    }
  },
})

if (isSelfTest) {
  const result = await recordCustomToolCall.execute({ message: "self-test" })
  process.stdout.write(`self-test=${JSON.stringify(result)}\n`)
  process.exit(0)
}

const result = await runAgent({
  apiKey,
  providerId,
  modelId,
  maxIterations: 3,
  tools: [recordCustomToolCall],
  prompt,
  // Demo streams the assistant reply as primary output.
  textStream: process.stdout,
})
if (result.status !== "completed") {
  throw result.error ?? new Error(`Agent run ${result.status}`)
}
process.stdout.write(`\nstatus=${result.status}\n`)
