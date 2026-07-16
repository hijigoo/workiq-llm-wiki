import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { config } from "./config.js";

/**
 * Open an authenticated MCP client, run `fn`, then always close it.
 * The bearer token is attached to every HTTP request via requestInit headers.
 */
export async function withMcp(accessToken, fn) {
  if (!accessToken) throw new Error("Not signed in (no access token).");

  const transport = new StreamableHTTPClientTransport(new URL(config.mcpServerUrl), {
    requestInit: {
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  });

  const client = new Client(
    { name: "mail-mcp-web-sample", version: "1.0.0" },
    { capabilities: {} }
  );

  try {
    await client.connect(transport);
    return await fn(client);
  } finally {
    try {
      await client.close();
    } catch {
      /* ignore close errors */
    }
  }
}

export async function listTools(accessToken) {
  return withMcp(accessToken, async (client) => {
    const res = await client.listTools();
    return res.tools || [];
  });
}

export async function callTool(accessToken, name, args) {
  return withMcp(accessToken, async (client) => {
    return client.callTool({ name, arguments: args || {} });
  });
}

/** Flatten an MCP tool result's content array into a readable string. */
export function contentToText(result) {
  if (!result) return "";
  if (result.isError) {
    const text = (result.content || [])
      .map((c) => (c.type === "text" ? c.text : JSON.stringify(c)))
      .join("\n");
    return `ERROR: ${text}`;
  }
  const parts = (result.content || []).map((c) => {
    if (c.type === "text") return c.text;
    return "```json\n" + JSON.stringify(c, null, 2) + "\n```";
  });
  return parts.join("\n");
}
