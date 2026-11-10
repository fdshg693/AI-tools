import { createTool } from "@cline/sdk"

/**
 * Build a completesRun tool that captures its input via a closure.
 * Returns `{ tool, getResult }` so callers can read the submitted value after the run.
 *
 * @param {{
 *   name: string,
 *   description: string,
 *   inputSchema: import("zod").ZodType,
 *   formatResult?: (input: unknown) => unknown,
 * }} opts
 */
export function createCompletingTool({
  name,
  description,
  inputSchema,
  formatResult = () => ({ ok: true }),
}) {
  let result = null
  const tool = createTool({
    name,
    description,
    inputSchema,
    lifecycle: { completesRun: true },
    async execute(input) {
      result = input
      return formatResult(input)
    },
  })
  return {
    tool,
    getResult: () => result,
  }
}
