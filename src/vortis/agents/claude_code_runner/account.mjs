import { query } from "@anthropic-ai/claude-agent-sdk";

const OUTPUT_START = "---VORTIS_OUTPUT_START---";
const OUTPUT_END = "---VORTIS_OUTPUT_END---";
const TOOL_PREFIX = "mcp__vortis__";
const BUILTIN_TOOLS = [
  "Agent",
  "Bash",
  "BashOutput",
  "Edit",
  "ExitPlanMode",
  "Glob",
  "Grep",
  "KillShell",
  "MultiEdit",
  "NotebookEdit",
  "Read",
  "Task",
  "TodoWrite",
  "Write",
];
const WEB_TOOLS = ["WebSearch", "WebFetch"];
const AUTH_HINTS = ["/login", "not logged in", "invalid api key", "authentication", "oauth", "401"];

function emit(response) {
  console.log(OUTPUT_START);
  console.log(JSON.stringify(response));
  console.log(OUTPUT_END);
}

async function readStdin() {
  let data = "";
  process.stdin.setEncoding("utf-8");
  for await (const chunk of process.stdin) data += chunk;
  return data;
}

function text(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => (part && part.type === "text" ? part.text : JSON.stringify(part ?? "")))
      .join("\n");
  }
  return JSON.stringify(content ?? "");
}

function buildOptions(request) {
  const web = request.web !== false;
  const options = {
    maxTurns: request.max_turns || 20,
    settingSources: [],
    disallowedTools: web ? BUILTIN_TOOLS : [...BUILTIN_TOOLS, ...WEB_TOOLS],
    allowedTools: web ? ["mcp__vortis", ...WEB_TOOLS] : ["mcp__vortis"],
  };
  if (request.model) options.model = request.model;
  if (request.system_prompt) options.systemPrompt = request.system_prompt;
  if (request.workspace) options.cwd = request.workspace;
  if (request.mcp?.url) {
    options.mcpServers = {
      vortis: {
        type: "http",
        url: request.mcp.url,
        headers: { Authorization: `Bearer ${request.mcp.token}` },
      },
    };
  }
  return options;
}

async function main() {
  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (error) {
    emit({ content: `Invalid request: ${error}`, tool_results: [], metadata: { error: true } });
    process.exitCode = 1;
    return;
  }

  delete process.env.ANTHROPIC_API_KEY;
  delete process.env.ANTHROPIC_AUTH_TOKEN;

  let content = "";
  const toolResults = [];
  const pending = new Map();
  const metadata = {};

  try {
    for await (const message of query({ prompt: request.prompt, options: buildOptions(request) })) {
      if (message.type === "system" && message.subtype === "init") {
        metadata.model = message.model;
        metadata.session_id = message.session_id;
      } else if (message.type === "assistant") {
        for (const block of message.message?.content ?? []) {
          if (block.type === "text" && block.text) {
            content = block.text;
          } else if (block.type === "tool_use") {
            pending.set(block.id, toolResults.length);
            toolResults.push({
              tool_name: block.name.startsWith(TOOL_PREFIX) ? block.name.slice(TOOL_PREFIX.length) : block.name,
              arguments: block.input ?? {},
              content: "",
              success: true,
            });
          }
        }
      } else if (message.type === "user") {
        const blocks = Array.isArray(message.message?.content) ? message.message.content : [];
        for (const block of blocks) {
          if (block.type !== "tool_result") continue;
          const index = pending.get(block.tool_use_id);
          if (index === undefined) continue;
          toolResults[index].content = text(block.content);
          toolResults[index].success = !block.is_error;
        }
      } else if (message.type === "result") {
        metadata.turns = message.num_turns;
        metadata.duration_ms = message.duration_ms;
        if (message.usage) {
          metadata.prompt_tokens = message.usage.input_tokens ?? 0;
          metadata.completion_tokens = message.usage.output_tokens ?? 0;
          metadata.total_tokens = metadata.prompt_tokens + metadata.completion_tokens;
        }
        if (message.is_error || message.subtype !== "success") {
          const detail = message.subtype === "success" ? message.result : (message.errors ?? []).join("\n");
          throw new Error(detail || message.subtype || "Claude request failed");
        }
        content = message.result || content;
      }
    }
    emit({ content, tool_results: toolResults, metadata });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    const lower = detail.toLowerCase();
    metadata.error = true;
    metadata.auth_error = AUTH_HINTS.some((hint) => lower.includes(hint));
    emit({ content: detail, tool_results: toolResults, metadata });
    process.exitCode = 1;
  }
}

await main();
