import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

/**
 * Locate the bundled `@github/copilot` runtime entrypoint for the current
 * platform ourselves and return it, to set as `COPILOT_CLI_PATH`.
 *
 * pnpm's isolated node_modules only exposes a package to the code of
 * packages that actually declare it as a dependency. `@github/copilot-sdk`
 * looks up its platform package (e.g. `@github/copilot-win32-x64`) from its
 * own file location, which under pnpm cannot see `@github/copilot`'s private
 * node_modules — so it throws "Could not resolve a @github/copilot platform
 * package" even though everything is installed. Declaring `@github/copilot`
 * as our own direct dependency (see package.json) makes it resolvable from
 * here, and its platform package sits right next to it in the same
 * private node_modules folder, so we can build the path ourselves.
 */
export function resolveBundledCliPath() {
  const req = createRequire(import.meta.url);
  let copilotPkgJsonPath;
  try {
    copilotPkgJsonPath = req.resolve("@github/copilot/package.json");
  } catch {
    return undefined;
  }
  const scopeDir = dirname(dirname(copilotPkgJsonPath)); // .../node_modules/@github/copilot/package.json -> .../node_modules/@github
  const variants =
    process.platform === "linux" ? ["linux", "linuxmusl"] : [process.platform];
  for (const variant of variants) {
    const candidate = join(
      scopeDir,
      `copilot-${variant}-${process.arch}`,
      "index.js",
    );
    if (existsSync(candidate)) return candidate;
  }
  return undefined;
}
