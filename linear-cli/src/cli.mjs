#!/usr/bin/env node
import { parseArgs } from "node:util";
import process from "node:process";
import { loadLocalEnv, readPackageVersion } from "./env.mjs";
import { createClient } from "./client.mjs";
import { loadConfig } from "./config.mjs";
import { searchIssues } from "./search.mjs";
import { updateIssue } from "./update.mjs";
import { addComment, listComments, deleteComment } from "./comment.mjs";
import { createIssue } from "./create.mjs";
import { getIssue } from "./show.mjs";

async function readStdin() {
  if (process.stdin.isTTY) return null;
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString("utf8").trim();
  return text.length > 0 ? text : null;
}

function printSearchTable(issues) {
  if (issues.length === 0) {
    console.log("(no results)");
    return;
  }
  console.log(["identifier", "status", "assignee", "title", "url"].join("\t"));
  for (const issue of issues) {
    console.log(
      [issue.identifier, issue.status ?? "", issue.assignee ?? "", issue.title, issue.url].join(
        "\t",
      ),
    );
  }
}

async function runSearch(rawArgs) {
  const { values } = parseArgs({
    args: rawArgs,
    options: {
      team: { type: "string" },
      project: { type: "string" },
      status: { type: "string" },
      assignee: { type: "string" },
      title: { type: "string" },
      label: { type: "string" },
      limit: { type: "string", default: "50" },
      json: { type: "boolean", default: false },
    },
  });

  const config = loadConfig();
  const team = values.team ?? config.team;
  const project = values.project ?? config.project;

  const client = createClient();
  const issues = await searchIssues(client, {
    team,
    project,
    status: values.status,
    assignee: values.assignee,
    title: values.title,
    label: values.label,
    limit: Number(values.limit),
  });

  if (values.json) {
    console.log(JSON.stringify(issues, null, 2));
  } else {
    printSearchTable(issues);
  }
}

async function runUpdate(rawArgs) {
  const { values, positionals } = parseArgs({
    args: rawArgs,
    allowPositionals: true,
    options: {
      status: { type: "string" },
      assignee: { type: "string" },
      "add-label": { type: "string", multiple: true },
      "remove-label": { type: "string", multiple: true },
      description: { type: "string" },
      json: { type: "boolean", default: false },
    },
  });

  const [issueId] = positionals;
  if (!issueId) {
    throw new Error(
      "Usage: linear-cli update <issue-id> [--status <name>] [--assignee <email|none>] [--add-label <name>...] [--remove-label <name>...] [--description <text>]",
    );
  }

  const client = createClient();
  const result = await updateIssue(client, issueId, {
    status: values.status,
    assignee: values.assignee,
    addLabels: values["add-label"],
    removeLabels: values["remove-label"],
    description: values.description,
  });

  if (values.json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log(`Updated ${result.identifier} (success: ${result.success})`);
  }
}

async function runComment(rawArgs) {
  const { values, positionals } = parseArgs({
    args: rawArgs,
    allowPositionals: true,
    options: {
      body: { type: "string" },
      json: { type: "boolean", default: false },
    },
  });

  const [issueId] = positionals;
  if (!issueId) {
    throw new Error("Usage: linear-cli comment <issue-id> [--body <text>]");
  }

  const body = values.body ?? (await readStdin());
  if (!body) {
    throw new Error("コメント本文を --body または標準入力で指定してください。");
  }

  const client = createClient();
  const result = await addComment(client, issueId, body);

  if (values.json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log(`Added comment to ${issueId}: ${result.url ?? "(no url)"}`);
  }
}

async function runCreate(rawArgs) {
  const { values } = parseArgs({
    args: rawArgs,
    options: {
      title: { type: "string" },
      team: { type: "string" },
      project: { type: "string" },
      description: { type: "string" },
      label: { type: "string", multiple: true },
      json: { type: "boolean", default: false },
    },
  });

  const config = loadConfig();
  const team = values.team ?? config.team;
  const project = values.project ?? config.project;

  const client = createClient();
  const result = await createIssue(client, {
    title: values.title,
    team,
    project,
    description: values.description,
    labels: values.label,
  });

  if (values.json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log(`Created ${result.identifier}: ${result.url ?? "(no url)"}`);
  }
}

async function runComments(rawArgs) {
  const { values, positionals } = parseArgs({
    args: rawArgs,
    allowPositionals: true,
    options: {
      json: { type: "boolean", default: false },
    },
  });

  const [issueId] = positionals;
  if (!issueId) {
    throw new Error("Usage: linear-cli comments <issue-id>");
  }

  const client = createClient();
  const comments = await listComments(client, issueId);

  if (values.json) {
    console.log(JSON.stringify(comments, null, 2));
  } else if (comments.length === 0) {
    console.log("(no comments)");
  } else {
    for (const comment of comments) {
      console.log(`--- ${comment.id} (${comment.createdAt}) ---`);
      console.log(comment.body);
    }
  }
}

async function runCommentDelete(rawArgs) {
  const { values, positionals } = parseArgs({
    args: rawArgs,
    allowPositionals: true,
    options: {
      json: { type: "boolean", default: false },
    },
  });

  const [commentId] = positionals;
  if (!commentId) {
    throw new Error("Usage: linear-cli comment-delete <comment-id>");
  }

  const client = createClient();
  const result = await deleteComment(client, commentId);

  if (values.json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log(`Deleted comment ${commentId} (success: ${result.success})`);
  }
}

async function runShow(rawArgs) {
  const { values, positionals } = parseArgs({
    args: rawArgs,
    allowPositionals: true,
    options: {
      json: { type: "boolean", default: false },
    },
  });

  const [issueId] = positionals;
  if (!issueId) {
    throw new Error("Usage: linear-cli show <issue-id>");
  }

  const client = createClient();
  const issue = await getIssue(client, issueId);

  if (values.json) {
    console.log(JSON.stringify(issue, null, 2));
  } else {
    console.log(`${issue.identifier}: ${issue.title}`);
    console.log(`status: ${issue.status ?? ""}`);
    console.log(`assignee: ${issue.assignee ?? ""}`);
    console.log(`project: ${issue.project ?? ""}`);
    console.log(`labels: ${issue.labels.join(", ")}`);
    console.log(`url: ${issue.url}`);
    console.log("---");
    console.log(issue.description ?? "");
  }
}

async function main() {
  const argv = process.argv.slice(2);

  if (argv.length === 1 && argv[0] === "--version") {
    console.log(`linear-cli ${readPackageVersion()}`);
    return;
  }

  const [subcommand, ...rest] = argv;

  loadLocalEnv();

  switch (subcommand) {
    case "search":
      await runSearch(rest);
      break;
    case "update":
      await runUpdate(rest);
      break;
    case "comment":
      await runComment(rest);
      break;
    case "create":
      await runCreate(rest);
      break;
    case "comments":
      await runComments(rest);
      break;
    case "comment-delete":
      await runCommentDelete(rest);
      break;
    case "show":
      await runShow(rest);
      break;
    default:
      console.error(
        `Unknown subcommand: ${subcommand ?? "(none)"}\nUsage: linear-cli <search|update|comment|create|comments|comment-delete|show>`,
      );
      process.exitCode = 1;
  }
}

try {
  await main();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
