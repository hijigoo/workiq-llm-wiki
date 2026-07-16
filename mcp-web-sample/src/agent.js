import OpenAI, { AzureOpenAI } from "openai";
import { DefaultAzureCredential, getBearerTokenProvider } from "@azure/identity";
import { config, llmProvider, SOURCES } from "./config.js";
import { withMcps, contentToText } from "./mcp.js";

function makeOpenAI() {
  const provider = llmProvider();
  if (provider === "azure") {
    const common = {
      endpoint: config.llm.azureEndpoint,
      deployment: config.llm.azureDeployment,
      apiVersion: config.llm.azureApiVersion,
    };
    // Prefer Entra ID (Azure AD) auth; fall back to API key only if provided.
    if (config.llm.azureApiKey) {
      return {
        client: new AzureOpenAI({ ...common, apiKey: config.llm.azureApiKey }),
        model: config.llm.azureDeployment,
      };
    }
    const credential = new DefaultAzureCredential();
    const azureADTokenProvider = getBearerTokenProvider(
      credential,
      config.llm.azureTokenScope
    );
    return {
      client: new AzureOpenAI({ ...common, azureADTokenProvider }),
      model: config.llm.azureDeployment,
    };
  }
  if (provider === "openai") {
    return {
      client: new OpenAI({ apiKey: config.llm.openaiApiKey }),
      model: config.llm.openaiModel,
    };
  }
  return null;
}

/**
 * Build a per-turn OpenAI tool list plus a registry mapping each synthetic,
 * source-namespaced tool name back to { sourceKey, originalName }. We never
 * let the model's raw tool name be parsed for routing — it's always looked
 * up in this server-built registry, which also keeps names unique and under
 * OpenAI's function-name length limit even if the two MCP servers happen to
 * expose tools with the same original name.
 */
function buildToolset(toolsBySource) {
  const registry = new Map();
  const tools = [];
  const seen = new Map(); // dedupe key -> count, in case of name collisions after truncation

  for (const [sourceKey, mcpTools] of Object.entries(toolsBySource)) {
    for (const t of mcpTools) {
      const base = `${sourceKey}__${t.name}`.slice(0, 60);
      let unique = base;
      const count = seen.get(base) || 0;
      if (count > 0) unique = `${base}_${count}`.slice(0, 64);
      seen.set(base, count + 1);

      registry.set(unique, { sourceKey, originalName: t.name });
      tools.push({
        type: "function",
        function: {
          name: unique,
          description: `[${SOURCES[sourceKey]?.label || sourceKey}] ${t.description || t.name}`,
          parameters: t.inputSchema || { type: "object", properties: {} },
        },
      });
    }
  }
  return { tools, registry };
}

function buildSystemPrompt(sourceKeys) {
  const intros = sourceKeys
    .map((k) => SOURCES[k])
    .filter(Boolean)
    .map((s) => `--- ${s.label} tools ---\n${s.systemPrompt}`)
    .join("\n\n");

  return `You are a helpful assistant connected to one or more Microsoft "Work IQ" MCP servers.
Active sources for this conversation: ${sourceKeys.map((k) => SOURCES[k]?.label || k).join(", ") || "(none)"}.
Every tool name is prefixed with its source (e.g. "mail__..." or "teams__...") — only call tools that belong to a source relevant to the request.
Be careful about mixing data across sources: do not copy or forward content from one source (e.g. mail) into a write action on another source (e.g. posting to Teams) unless the user explicitly asked you to do that.
Answer in the user's language. Be concise. Never invent IDs — resolve names to IDs via a list/search tool first.

${intros}`;
}

/**
 * Run a tool-calling loop against one or more MCP servers at once.
 * `tokensBySource` is a map of sourceKey -> access token for every source the
 * caller wants active in this turn (already resolved/validated by the
 * server). Returns { answer, trace, sourceErrors } where trace lists each
 * tool call + result (tagged with source), and sourceErrors reports any
 * source that failed to connect (the loop still proceeds with the rest).
 */
export async function runAgent(tokensBySource, userMessage, history = []) {
  const oa = makeOpenAI();
  if (!oa) {
    const err = new Error("LLM_NOT_CONFIGURED");
    err.code = "LLM_NOT_CONFIGURED";
    throw err;
  }

  const sourceKeys = Object.keys(tokensBySource);
  if (sourceKeys.length === 0) {
    const err = new Error("NO_SOURCE_SELECTED");
    err.code = "NO_SOURCE_SELECTED";
    throw err;
  }

  return withMcps(tokensBySource, async (clients, connectErrors) => {
    const sourceErrors = Object.fromEntries(
      Object.entries(connectErrors).map(([k, e]) => [k, e.message])
    );
    const connectedKeys = Object.keys(clients);

    const toolsBySource = {};
    await Promise.allSettled(
      connectedKeys.map(async (sourceKey) => {
        try {
          const res = await clients[sourceKey].listTools();
          toolsBySource[sourceKey] = res.tools || [];
        } catch (e) {
          sourceErrors[sourceKey] = e.message;
        }
      })
    );

    const { tools, registry } = buildToolset(toolsBySource);
    const messages = [
      { role: "system", content: buildSystemPrompt(sourceKeys) },
      ...history,
      { role: "user", content: userMessage },
    ];
    const trace = [];

    if (tools.length === 0) {
      return {
        answer:
          "선택된 소스에서 사용할 수 있는 도구가 없습니다. 연결 상태를 확인하세요.",
        trace,
        sourceErrors,
      };
    }

    for (let i = 0; i < 8; i++) {
      const completion = await oa.client.chat.completions.create({
        model: oa.model,
        messages,
        tools,
        tool_choice: "auto",
        temperature: 0,
      });

      const msg = completion.choices[0].message;
      messages.push(msg);

      if (!msg.tool_calls || msg.tool_calls.length === 0) {
        return { answer: msg.content || "(no content)", trace, sourceErrors };
      }

      for (const call of msg.tool_calls) {
        let args = {};
        try {
          args = call.function.arguments ? JSON.parse(call.function.arguments) : {};
        } catch {
          args = {};
        }

        const entry = registry.get(call.function.name);
        let resultText;
        if (!entry) {
          resultText = `ERROR: unknown tool "${call.function.name}"`;
        } else {
          const { sourceKey, originalName } = entry;
          const client = clients[sourceKey];
          if (!client) {
            resultText = `ERROR: source "${sourceKey}" is not connected`;
          } else {
            try {
              const result = await client.callTool({ name: originalName, arguments: args });
              resultText = contentToText(result);
            } catch (e) {
              resultText = `ERROR calling ${originalName}: ${e.message}`;
            }
          }
        }

        trace.push({
          tool: entry?.originalName || call.function.name,
          source: entry?.sourceKey,
          args,
          result: resultText,
        });
        messages.push({
          role: "tool",
          tool_call_id: call.id,
          content: resultText.slice(0, 8000),
        });
      }
    }

    return {
      answer: "Reached the tool-call limit without a final answer. See the trace below.",
      trace,
      sourceErrors,
    };
  });
}
