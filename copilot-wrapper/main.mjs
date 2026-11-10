#!/usr/bin/env node
// BYOK (Bring Your Own Key) 経由で OpenAI 互換モデルを GitHub Copilot SDK から呼び出す CLI。
// 設定・ツール・実行オプションをコマンドライン引数で指定して1ターンだけ実行する。
import { CopilotClient, approveAll } from "@github/copilot-sdk";
import { resolveBundledCliPath } from "./lib/cliPath.mjs";
import { resolveConfig } from "./lib/config.mjs";
import { ENV_PATH, loadDotenv } from "./lib/dotenv.mjs";
import { AVAILABLE_TOOL_NAMES, resolveTools } from "./lib/tools.mjs";

loadDotenv(ENV_PATH);

// Work around a pnpm-vs-copilot-sdk platform-package resolution gap; see lib/cliPath.mjs.
if (!process.env.COPILOT_CLI_PATH) {
  const cliPath = resolveBundledCliPath();
  if (cliPath) process.env.COPILOT_CLI_PATH = cliPath;
}

const HELP = `Usage: node main.mjs [options] "<prompt>"

BYOK (Bring Your Own Key) 経由で OpenAI 互換 API のモデルを Copilot SDK から呼び出す。
プロンプトは引数または標準入力から渡す。

Connection options (fall back to tools/copilot-wrapper/.env):
  -m, --model <id>              モデルID（必須）
      --base-url <url>          API エンドポイントのベースURL（必須）
      --api-key <key>           APIキー（ローカルプロバイダーでは省略可）
      --provider-type <type>    openai | azure | anthropic（既定: openai）
      --wire-api <api>          completions | responses（既定: completions）
      --azure-api-version <v>   providerType=azure のときのAPIバージョン
      --github-token <token>    Copilot SDKランタイム自体を認証するGitHubトークン（BYOK運用では通常不要）
      --use-logged-in-user      ログイン済みユーザー/gh CLI認証をSDKランタイムに使わせる（既定: 使わない）

Run options:
  -p, --prompt <text>           プロンプト（省略時は末尾の位置引数、それも無ければ標準入力）
      --system <text>           システムメッセージに追記する内容
      --reasoning-effort <e>    low | medium | high | xhigh | max
      --stream                  ストリーミング出力を有効にする
      --tool <name>             有効化するツール名（複数指定可）。--list-tools で一覧表示
      --approve-all             shell/write等すべてのツール実行を自動承認する（危険。既定は read/custom-toolのみ自動承認）
      --working-directory <p>   セッションの作業ディレクトリ
      --json                    最終応答をテキストではなくJSONで出力する
      --list-tools               利用可能なツール名の一覧を表示して終了する
  -h, --help                    このヘルプを表示する

Available tools: ${AVAILABLE_TOOL_NAMES.join(", ")}

Examples:
  node main.mjs --model llama3 --base-url http://localhost:11434/v1 -p "1+1="
  node main.mjs --tool get_time --tool http_get --approve-all -p "現在時刻を教えて"
`;

function parseArgs(argv) {
  const flags = { tools: [] };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "-h":
      case "--help":
        flags.help = true;
        break;
      case "--list-tools":
        flags.listTools = true;
        break;
      case "-m":
      case "--model":
        flags.model = argv[++i];
        break;
      case "--base-url":
        flags.baseUrl = argv[++i];
        break;
      case "--api-key":
        flags.apiKey = argv[++i];
        break;
      case "--provider-type":
        flags.providerType = argv[++i];
        break;
      case "--wire-api":
        flags.wireApi = argv[++i];
        break;
      case "--azure-api-version":
        flags.azureApiVersion = argv[++i];
        break;
      case "--github-token":
        flags.gitHubToken = argv[++i];
        break;
      case "--use-logged-in-user":
        flags.useLoggedInUser = true;
        break;
      case "-p":
      case "--prompt":
        flags.prompt = argv[++i];
        break;
      case "--system":
        flags.system = argv[++i];
        break;
      case "--reasoning-effort":
        flags.reasoningEffort = argv[++i];
        break;
      case "--stream":
        flags.stream = true;
        break;
      case "--tool":
        flags.tools.push(argv[++i]);
        break;
      case "--approve-all":
        flags.approveAll = true;
        break;
      case "--working-directory":
        flags.workingDirectory = argv[++i];
        break;
      case "--json":
        flags.json = true;
        break;
      default:
        positional.push(a);
    }
  }
  if (!flags.prompt && positional.length > 0)
    flags.prompt = positional.join(" ");
  return flags;
}

async function readStdin() {
  if (process.stdin.isTTY) return "";
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf-8").trim();
}

function makePermissionHandler(allowAll) {
  if (allowAll) return approveAll;
  return (request) => {
    if (
      "managedApprovalRequired" in request &&
      request.managedApprovalRequired === true
    ) {
      return { kind: "no-result" };
    }
    if (request.kind === "custom-tool" || request.kind === "read") {
      return { kind: "approve-once" };
    }
    return {
      kind: "reject",
      feedback: `"${request.kind}" requests are denied by default in this wrapper. Re-run with --approve-all to allow them.`,
    };
  };
}

async function main() {
  const flags = parseArgs(process.argv.slice(2));

  if (flags.help) {
    process.stdout.write(HELP);
    return;
  }
  if (flags.listTools) {
    process.stdout.write(`${AVAILABLE_TOOL_NAMES.join("\n")}\n`);
    return;
  }

  if (!flags.prompt) flags.prompt = await readStdin();
  if (!flags.prompt) {
    process.stderr.write(
      "Error: a prompt is required (argument, --prompt, or stdin)\n\n",
    );
    process.stderr.write(HELP);
    process.exitCode = 1;
    return;
  }

  const config = resolveConfig(flags);
  const tools = resolveTools(flags.tools);

  const client = new CopilotClient({
    useLoggedInUser: config.useLoggedInUser,
    gitHubToken: config.gitHubToken,
    workingDirectory: flags.workingDirectory,
  });
  await client.start();

  try {
    const session = await client.createSession({
      model: config.model,
      provider: config.provider,
      tools,
      reasoningEffort: config.reasoningEffort,
      streaming: config.streaming,
      systemMessage: config.systemMessage
        ? { content: config.systemMessage }
        : undefined,
      workingDirectory: flags.workingDirectory,
      onPermissionRequest: makePermissionHandler(flags.approveAll),
    });

    let finalEvent;
    const done = new Promise((res) => {
      if (config.streaming) {
        session.on("assistant.message_delta", (event) => {
          process.stderr.write(event.data.deltaContent);
        });
      }
      session.on("assistant.message", (event) => {
        finalEvent = event;
      });
      session.on("session.idle", () => res());
      session.on("session.error", (event) => {
        process.stderr.write(`\n[session.error] ${event.data.message}\n`);
        res();
      });
    });

    await session.send({ prompt: flags.prompt });
    await done;

    if (config.streaming) process.stderr.write("\n");

    if (!finalEvent) {
      process.stderr.write("Error: no response received from the model\n");
      process.exitCode = 1;
    } else if (flags.json) {
      process.stdout.write(`${JSON.stringify(finalEvent.data, null, 2)}\n`);
    } else {
      process.stdout.write(`${finalEvent.data.content}\n`);
    }

    await session.disconnect();
  } finally {
    await client.stop();
  }
}

main().catch((error) => {
  process.stderr.write(`Error: ${error.message}\n`);
  process.exitCode = 1;
});
