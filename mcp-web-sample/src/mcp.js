import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { SOURCES } from "./config.js";

function sourceOrThrow(sourceKey) {
  const source = SOURCES[sourceKey];
  if (!source) throw new Error(`Unknown MCP source: ${sourceKey}`);
  return source;
}

/**
 * Open an authenticated MCP client for ONE source, run `fn`, then always
 * close it. The bearer token is attached to every HTTP request via
 * requestInit headers. Connections are request-scoped (never pooled across
 * requests) to avoid sharing/expiry issues when multiple sources and users
 * are involved.
 */
export async function withMcp(accessToken, sourceKey, fn) {
  if (!accessToken) throw new Error(`Not signed in to ${sourceKey} (no access token).`);
  const source = sourceOrThrow(sourceKey);

  const transport = new StreamableHTTPClientTransport(new URL(source.mcpServerUrl), {
    requestInit: {
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  });

  const client = new Client({ name: source.clientName, version: "1.0.0" }, { capabilities: {} });

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

/**
 * Open authenticated MCP clients for MULTIPLE sources at once (used by the
 * agent's tool-calling loop, which may need to call either backend across
 * iterations), run `fn({ [sourceKey]: client })`, then always close all
 * clients. One source failing to connect does not block the others — it is
 * reported back via the `errors` map passed to `fn`.
 */
export async function withMcps(tokensBySource, fn) {
  const sourceKeys = Object.keys(tokensBySource);
  const opened = {};
  const errors = {};

  await Promise.allSettled(
    sourceKeys.map(async (sourceKey) => {
      const source = sourceOrThrow(sourceKey);
      const accessToken = tokensBySource[sourceKey];
      if (!accessToken) {
        errors[sourceKey] = new Error(`Not signed in to ${sourceKey} (no access token).`);
        return;
      }
      const transport = new StreamableHTTPClientTransport(new URL(source.mcpServerUrl), {
        requestInit: { headers: { Authorization: `Bearer ${accessToken}` } },
      });
      const client = new Client({ name: source.clientName, version: "1.0.0" }, { capabilities: {} });
      try {
        await client.connect(transport);
        opened[sourceKey] = client;
      } catch (e) {
        errors[sourceKey] = e;
      }
    })
  );

  try {
    return await fn(opened, errors);
  } finally {
    await Promise.allSettled(Object.values(opened).map((client) => client.close()));
  }
}

export async function listTools(accessToken, sourceKey) {
  return withMcp(accessToken, sourceKey, async (client) => {
    const res = await client.listTools();
    return res.tools || [];
  });
}

export async function callTool(accessToken, sourceKey, name, args) {
  return withMcp(accessToken, sourceKey, async (client) => {
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
