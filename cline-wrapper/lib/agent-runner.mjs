import { Agent } from "@cline/sdk"
import { DEFAULT_MODEL_ID, DEFAULT_PROVIDER_ID } from "./config.mjs"

/**
 * Construct an Agent, subscribe to progress events, run the prompt, then unsubscribe.
 *
 * Assistant text deltas go to `textStream` (default: stderr). Tool start/finish
 * always go to stderr. Pass `process.stdout` for demos that stream the reply
 * as the primary output (e.g. main.mjs).
 *
 * @param {{
 *   apiKey: string,
 *   providerId?: string,
 *   modelId?: string,
 *   systemPrompt?: string,
 *   tools?: unknown[],
 *   prompt: string,
 *   maxIterations?: number,
 *   label?: string,
 *   textStream?: NodeJS.WritableStream,
 * }} opts
 */
export function runAgent({
  apiKey,
  providerId = DEFAULT_PROVIDER_ID,
  modelId = DEFAULT_MODEL_ID,
  systemPrompt,
  tools,
  prompt,
  maxIterations,
  label,
  textStream = process.stderr,
}) {
  const agent = new Agent({
    providerId,
    modelId,
    apiKey,
    systemPrompt,
    maxIterations,
    tools,
  })
  const toolPrefix = label ? `${label}:` : ""
  const unsubscribe = agent.subscribe((event) => {
    if (event.type === "assistant-text-delta") {
      textStream.write(event.text ?? "")
    } else if (event.type === "tool-started") {
      process.stderr.write(`\n[${toolPrefix}tool-started] ${event.toolCall.toolName}\n`)
    } else if (event.type === "tool-finished") {
      process.stderr.write(`[${toolPrefix}tool-finished] ${event.toolCall.toolName}\n`)
    }
  })
  return agent.run(prompt).finally(unsubscribe)
}
