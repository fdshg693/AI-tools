// Shared repo search tools (pure Node, no external deps except @cline/sdk createTool).
// Extracted so the logic can be unit-tested without an API key or model call.

import { readFileSync, readdirSync, statSync } from "node:fs"
import { join, relative, resolve, sep } from "node:path"
import { createTool } from "@cline/sdk"
import { z } from "zod"

export const SKIP_DIRS = new Set([
  "node_modules", ".git", ".hg", ".svn", "dist", "build", ".next", ".turbo",
  ".vercel", "coverage", ".cache", "__pycache__", ".venv", "venv", ".tox",
])
export const MAX_GREP_MATCHES = 60
export const MAX_LINE_PREVIEW = 240
export const MAX_GREP_FILES = 4000
export const MAX_READ_BYTES = 60_000
export const MAX_LIST_FILES = 800

export function isTextFile(path) {
  try {
    const buf = readFileSync(path)
    if (buf.length === 0) return true
    if (buf.includes(0)) return false // NUL byte => binary
    return true
  } catch {
    return false
  }
}

export function walkFiles(root, onFile, maxFiles) {
  const stack = [root]
  let count = 0
  while (stack.length) {
    const dir = stack.pop()
    let entries
    try {
      entries = readdirSync(dir, { withFileTypes: true })
    } catch {
      continue
    }
    for (const e of entries) {
      if (count >= maxFiles) return
      const full = join(dir, e.name)
      if (e.isDirectory()) {
        if (!SKIP_DIRS.has(e.name)) stack.push(full)
      } else if (e.isFile()) {
        count++
        onFile(full)
      }
    }
  }
}

export function safeJoin(root, rel) {
  const target = resolve(root, rel ?? ".")
  if (target !== root && !target.startsWith(root + sep)) {
    throw new Error(`path outside repo root: ${rel}`)
  }
  return target
}

export function globToRegex(glob) {
  return glob ? new RegExp(glob.replace(/\./g, "\\.").replace(/\*/g, ".*") + "$") : null
}

export function makeRepoTools(root) {
  const grepSearch = createTool({
    name: "grep_search",
    description:
      "Search the repository with a regular expression (tested per line, case-insensitive by default). " +
      "Returns matching files, line numbers, and a short preview of each match (raw file contents are NOT returned beyond the preview). " +
      "Use this to discover which files reference a keyword/pattern. Glob filter is optional (e.g. '*.py').",
    inputSchema: z.object({
      pattern: z.string().min(1).describe("Regular expression to match per line."),
      path: z
        .string()
        .optional()
        .describe("Directory to search, relative to repo root. Defaults to repo root."),
      glob: z.string().optional().describe("Optional file-extension filter like '*.py' or '*.mjs'."),
      caseSensitive: z.boolean().optional().describe("Case-sensitive match. Defaults to false."),
    }),
    async execute(input) {
      const flags = input.caseSensitive ? "u" : "giu"
      let re
      try {
        re = new RegExp(input.pattern, flags)
      } catch (err) {
        return { ok: false, error: `invalid regex: ${err.message}`, matches: [] }
      }
      let base
      let st
      try {
        base = safeJoin(root, input.path)
        st = statSync(base)
      } catch (err) {
        return { ok: false, error: err.message, matches: [] }
      }
      const files = []
      const globRe = globToRegex(input.glob)
      const collect = (f) => {
        if (globRe && !globRe.test(f)) return
        files.push(f)
      }
      if (st.isFile()) {
        collect(base)
      } else {
        walkFiles(base, collect, MAX_GREP_FILES)
      }
      const matches = []
      let scanned = 0
      for (const file of files) {
        if (matches.length >= MAX_GREP_MATCHES) break
        if (!isTextFile(file)) continue
        scanned++
        let content
        try {
          content = readFileSync(file, "utf-8")
        } catch {
          continue
        }
        const lines = content.split(/\r?\n/)
        for (let i = 0; i < lines.length; i++) {
          if (matches.length >= MAX_GREP_MATCHES) break
          if (re.test(lines[i])) {
            matches.push({
              path: relative(root, file).split(sep).join("/"),
              line: i + 1,
              preview: lines[i].slice(0, MAX_LINE_PREVIEW),
            })
          }
        }
      }
      return {
        ok: true,
        pattern: input.pattern,
        filesScanned: scanned,
        truncated: matches.length >= MAX_GREP_MATCHES,
        matches,
      }
    },
  })


  const readFile = createTool({
    name: "read_file",
    description:
      "Read a file from the repository, returning its content with 1-based line numbers. " +
      "Optionally limit to a line range with startLine/endLine. Output is capped to keep context small.",
    inputSchema: z.object({
      path: z.string().min(1).describe("File path relative to repo root."),
      startLine: z.number().int().min(1).optional().describe("1-based start line (inclusive)."),
      endLine: z.number().int().min(1).optional().describe("1-based end line (inclusive)."),
    }),
    async execute(input) {
      let content
      try {
        const target = safeJoin(root, input.path)
        content = readFileSync(target, "utf-8")
      } catch (err) {
        return { ok: false, error: `cannot read ${input.path}: ${err.message}` }
      }
      const lines = content.split(/\r?\n/)
      const start = Math.max(1, input.startLine ?? 1)
      const end = Math.min(lines.length, input.endLine ?? lines.length)
      const slice = lines.slice(start - 1, end)
      let numbered = ""
      let bytes = 0
      for (let i = 0; i < slice.length; i++) {
        const ln = start + i
        const row = `${String(ln).padStart(6)}| ${slice[i]}`
        bytes += row.length + 1
        if (bytes > MAX_READ_BYTES) {
          numbered += `... (truncated at ${MAX_READ_BYTES} bytes; use startLine/endLine to read further)\n`
          break
        }
        numbered += row + "\n"
      }
      return {
        ok: true,
        path: input.path,
        totalLines: lines.length,
        shownRange: [start, start + slice.length - 1],
        content: numbered,
      }
    },
  })


  const listFiles = createTool({
    name: "list_files",
    description:
      "List files under a directory (recursive), relative to repo root. Skips dependency/build folders. Useful for orientation before grepping.",
    inputSchema: z.object({
      path: z.string().optional().describe("Directory relative to repo root. Defaults to repo root."),
      glob: z.string().optional().describe("Optional extension filter like '*.ts'."),
    }),
    async execute(input) {
      let base
      let st
      try {
        base = safeJoin(root, input.path)
        st = statSync(base)
      } catch (err) {
        return { ok: false, error: err.message, files: [] }
      }
      if (!st.isDirectory()) {
        return { ok: false, error: `not a directory: ${input.path ?? "."}`, files: [] }
      }
      const files = []
      const globRe = globToRegex(input.glob)
      const collect = (f) => {
        if (globRe && !globRe.test(f)) return
        files.push(relative(root, f).split(sep).join("/"))
      }
      walkFiles(base, collect, MAX_LIST_FILES)
      files.sort()
      return { ok: true, truncated: files.length >= MAX_LIST_FILES, files }
    },
  })

  return { grepSearch, readFile, listFiles }
}

