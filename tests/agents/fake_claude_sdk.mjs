import { writeFileSync } from "node:fs";

async function rpc(server, body) {
  const res = await fetch(server.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...server.headers },
    body: JSON.stringify(body),
  });
  return res.status === 202 ? null : res.json();
}

export async function* query({ prompt, options }) {
  if (process.env.FAKE_SDK_RECORD) {
    writeFileSync(process.env.FAKE_SDK_RECORD, JSON.stringify({ prompt, options, env: Object.keys(process.env) }));
  }
  if (process.env.FAKE_SDK_FAIL) throw new Error(process.env.FAKE_SDK_FAIL);
  yield { type: "system", subtype: "init", model: options.model, session_id: "s1" };
  const server = options.mcpServers?.vortis;
  if (server) {
    await rpc(server, { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } });
    await rpc(server, { jsonrpc: "2.0", method: "notifications/initialized" });
    const call = await rpc(server, {
      jsonrpc: "2.0",
      id: 2,
      method: "tools/call",
      params: { name: "echo", arguments: { text: "hi" } },
    });
    yield {
      type: "assistant",
      message: { content: [{ type: "tool_use", id: "t1", name: "mcp__vortis__echo", input: { text: "hi" } }] },
    };
    yield {
      type: "user",
      message: { content: [{ type: "tool_result", tool_use_id: "t1", content: call.result.content, is_error: call.result.isError }] },
    };
  }
  yield { type: "assistant", message: { content: [{ type: "text", text: "draft" }] } };
  yield {
    type: "result",
    subtype: "success",
    is_error: false,
    result: "Gotovo.",
    num_turns: 2,
    duration_ms: 5,
    usage: { input_tokens: 10, output_tokens: 4 },
  };
}
