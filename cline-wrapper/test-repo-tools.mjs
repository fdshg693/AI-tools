// Smoke test for lib/repo-tools.mjs — exercises grep/read/list against the real
// repo without needing an API key or model call. Run: node test-repo-tools.mjs
import { resolve } from "node:path"
import { makeRepoTools } from "./lib/repo-tools.mjs"

const repoRoot = resolve(import.meta.dirname, "../..")
const { grepSearch, readFile, listFiles } = makeRepoTools(repoRoot)

function assert(cond, msg) {
  if (!cond) {
    console.error("FAIL: " + msg)
    process.exit(1)
  }
  console.log("ok: " + msg)
}

// grep: find a known token in this repo (e.g. "cline-pass" in lib/config.mjs)
const grep = await grepSearch.execute({ pattern: "cline-pass", glob: "*.mjs" })
assert(grep.ok, "grep returns ok")
assert(
  grep.matches.some((m) => m.path.endsWith("tools/cline-wrapper/lib/config.mjs")),
  "grep finds lib/config.mjs referencing cline-pass",
)
assert(grep.matches.every((m) => typeof m.line === "number" && m.preview.length > 0), "grep matches have line+preview")

// grep: invalid regex returns structured error (not thrown)
const bad = await grepSearch.execute({ pattern: "(", glob: "*.mjs" })
assert(!bad.ok && /invalid regex/i.test(bad.error), "invalid regex returns structured error")

// read_file: read a known file with a line range
const rf = await readFile.execute({ path: "tools/cline-wrapper/main.mjs", startLine: 1, endLine: 5 })
assert(rf.ok, "read_file returns ok")
assert(rf.totalLines > 0, "read_file reports totalLines")
assert(/import/.test(rf.content), "read_file content contains expected text")

// read_file: missing file returns structured error
const rfBad = await readFile.execute({ path: "does/not/exist.mjs" })
assert(!rfBad.ok, "read_file on missing path returns !ok")

// path traversal is blocked
const trav = await readFile.execute({ path: "../../../etc/passwd" })
assert(!trav.ok && /outside repo root/.test(trav.error), "path traversal is blocked")

// list_files: list the cline-wrapper dir
const lf = await listFiles.execute({ path: "tools/cline-wrapper" })
assert(lf.ok, "list_files returns ok")
assert(lf.files.some((p) => p.endsWith("main.mjs")), "list_files includes main.mjs")
assert(!lf.files.some((p) => p.includes("node_modules/")), "list_files skips node_modules")

console.log("\nAll repo-tool smoke tests passed.")
