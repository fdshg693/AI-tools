import { readFileSync } from "node:fs";
import { defineTool } from "@github/copilot-sdk";
import { z } from "zod";

/**
 * Demo custom tools the CLI can register on the session, one per name.
 * Enable a subset with `--tool <name>` (repeatable). See `--list-tools`.
 */
const TOOL_FACTORIES = {
  get_time: () =>
    defineTool("get_time", {
      description: "Return the current date and time in ISO 8601 (UTC).",
      parameters: z.object({}),
      skipPermission: true,
      handler: async () => new Date().toISOString(),
    }),

  read_text_file: () =>
    defineTool("read_text_file", {
      description:
        "Read a local text file (UTF-8) and return its content, truncated to 20000 characters.",
      parameters: z.object({
        path: z
          .string()
          .describe(
            "Path to the file to read, relative to the working directory or absolute.",
          ),
      }),
      skipPermission: true,
      handler: async ({ path }) => {
        const content = readFileSync(path, "utf-8");
        return content.length > 20000
          ? `${content.slice(0, 20000)}\n...[truncated]`
          : content;
      },
    }),

  http_get: () =>
    defineTool("http_get", {
      description:
        "Fetch a URL over HTTP(S) and return the response body as text (truncated to 20000 characters).",
      parameters: z.object({
        url: z.string().describe("The URL to fetch."),
      }),
      handler: async ({ url }) => {
        const res = await fetch(url);
        const text = await res.text();
        const body =
          text.length > 20000
            ? `${text.slice(0, 20000)}\n...[truncated]`
            : text;
        return `HTTP ${res.status}\n${body}`;
      },
    }),
};

export const AVAILABLE_TOOL_NAMES = Object.keys(TOOL_FACTORIES);

/** Resolve `--tool` names to SDK Tool instances. Throws on an unknown name. */
export function resolveTools(names) {
  return names.map((name) => {
    const factory = TOOL_FACTORIES[name];
    if (!factory) {
      throw new Error(
        `Unknown tool "${name}". Available: ${AVAILABLE_TOOL_NAMES.join(", ")}`,
      );
    }
    return factory();
  });
}
