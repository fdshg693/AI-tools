import { ENV_PATH, missingRequiredKeyMessage } from "./dotenv.mjs";

const PROVIDER_TYPES = ["openai", "azure", "anthropic"];
const WIRE_APIS = ["completions", "responses"];
const REASONING_EFFORTS = ["low", "medium", "high", "xhigh", "max"];

function truthy(value) {
  return value === "true" || value === "1";
}

/** Treats an empty string (unset .env value) the same as undefined. */
function orUndefined(value) {
  return value ? value : undefined;
}

/**
 * Merge CLI flags over `process.env` (already populated from .env by the caller)
 * into the BYOK provider config plus the run-level options.
 */
export function resolveConfig(flags) {
  const baseUrl = orUndefined(
    flags.baseUrl ?? process.env.COPILOT_BYOK_BASE_URL,
  );
  const apiKey = orUndefined(flags.apiKey ?? process.env.COPILOT_BYOK_API_KEY);
  const model = orUndefined(flags.model ?? process.env.COPILOT_BYOK_MODEL);
  const providerType =
    orUndefined(flags.providerType ?? process.env.COPILOT_BYOK_PROVIDER_TYPE) ??
    "openai";
  const wireApi = orUndefined(
    flags.wireApi ?? process.env.COPILOT_BYOK_WIRE_API,
  );
  const azureApiVersion = orUndefined(
    flags.azureApiVersion ?? process.env.COPILOT_BYOK_AZURE_API_VERSION,
  );
  const useLoggedInUser =
    flags.useLoggedInUser ??
    ("COPILOT_USE_LOGGED_IN_USER" in process.env
      ? truthy(process.env.COPILOT_USE_LOGGED_IN_USER)
      : false);
  const gitHubToken = orUndefined(
    flags.gitHubToken ?? process.env.COPILOT_GITHUB_TOKEN,
  );

  if (!baseUrl) {
    throw new Error(
      `${missingRequiredKeyMessage("COPILOT_BYOK_BASE_URL", ENV_PATH)}\n--base-url でも指定できます。`,
    );
  }
  if (!model) {
    throw new Error(
      `${missingRequiredKeyMessage("COPILOT_BYOK_MODEL", ENV_PATH)}\n--model でも指定できます。`,
    );
  }
  if (!PROVIDER_TYPES.includes(providerType)) {
    throw new Error(
      `--provider-type must be one of ${PROVIDER_TYPES.join(", ")}`,
    );
  }
  if (wireApi && !WIRE_APIS.includes(wireApi)) {
    throw new Error(`--wire-api must be one of ${WIRE_APIS.join(", ")}`);
  }
  if (
    flags.reasoningEffort &&
    !REASONING_EFFORTS.includes(flags.reasoningEffort)
  ) {
    throw new Error(
      `--reasoning-effort must be one of ${REASONING_EFFORTS.join(", ")}`,
    );
  }

  const provider = { type: providerType, baseUrl, apiKey };
  if (wireApi) provider.wireApi = wireApi;
  if (providerType === "azure" && azureApiVersion)
    provider.azure = { apiVersion: azureApiVersion };

  return {
    provider,
    model,
    useLoggedInUser,
    gitHubToken,
    reasoningEffort: flags.reasoningEffort,
    systemMessage: flags.system,
    streaming: flags.stream,
  };
}
