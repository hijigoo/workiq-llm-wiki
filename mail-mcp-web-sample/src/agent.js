import OpenAI, { AzureOpenAI } from "openai";
import { DefaultAzureCredential, getBearerTokenProvider } from "@azure/identity";
import { config, llmProvider } from "./config.js";
import { withMcp, contentToText } from "./mcp.js";

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

function toOpenAITools(mcpTools) {
  return mcpTools.map((t) => ({
    type: "function",
    function: {
      name: t.name,
      description: t.description || t.name,
      parameters: t.inputSchema || { type: "object", properties: {} },
    },
  }));
}

const SYSTEM_PROMPT = `You are a helpful assistant connected to the Microsoft "Work IQ Mail" MCP server (Microsoft Graph mail tools).
Use the available tools to fulfil the user's request about their mailbox: reading, searching, composing, replying to, sending, and managing email messages and drafts.
Rules:
- Prefer calling a tool over guessing. Resolve messages to IDs first (e.g. search/list messages) before acting on a specific one.
- IDs in the tools are real Microsoft Graph message IDs. Never invent an ID.
- For write actions (send mail, create/send draft, reply, reply-all, update, delete) do exactly what the user asked; summarise what you did.
- When composing HTML email, set the body contentType to "HTML" (and preferHtml where supported).
- Answer in the user's language. Be concise.`;

/**
 * Run a tool-calling loop against the Mail MCP server.
 * Returns { answer, trace } where trace lists each tool call + result.
 */
export async function runAgent(accessToken, userMessage, history = []) {
  const oa = makeOpenAI();
  if (!oa) {
    const err = new Error("LLM_NOT_CONFIGURED");
    err.code = "LLM_NOT_CONFIGURED";
    throw err;
  }

  return withMcp(accessToken, async (client) => {
    const mcpTools = (await client.listTools()).tools || [];
    const tools = toOpenAITools(mcpTools);

    const messages = [
      { role: "system", content: SYSTEM_PROMPT },
      ...history,
      { role: "user", content: userMessage },
    ];
    const trace = [];

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
        return { answer: msg.content || "(no content)", trace };
      }

      for (const call of msg.tool_calls) {
        let args = {};
        try {
          args = call.function.arguments ? JSON.parse(call.function.arguments) : {};
        } catch {
          args = {};
        }
        let resultText;
        try {
          const result = await client.callTool({ name: call.function.name, arguments: args });
          resultText = contentToText(result);
        } catch (e) {
          resultText = `ERROR calling ${call.function.name}: ${e.message}`;
        }
        trace.push({ tool: call.function.name, args, result: resultText });
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
    };
  });
}
