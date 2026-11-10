/** Default ClinePass provider/model used by main.mjs and repo-search.mjs. */
export const DEFAULT_PROVIDER_ID = "cline-pass"
export const DEFAULT_MODEL_ID = "cline-pass/minimax-m3"

/**
 * Resolve a CLI `--model` value to providerId + modelId.
 * Accepts a full id (`cline-pass/minimax-m3`) or a short name (`minimax-m3`).
 */
export function resolveModel(modelArg, providerId = DEFAULT_PROVIDER_ID) {
  if (!modelArg) {
    return { providerId, modelId: DEFAULT_MODEL_ID }
  }
  if (modelArg.includes("/")) {
    const slash = modelArg.indexOf("/")
    return {
      providerId: modelArg.slice(0, slash),
      modelId: modelArg,
    }
  }
  return {
    providerId,
    modelId: `${providerId}/${modelArg}`,
  }
}
