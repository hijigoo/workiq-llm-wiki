import dotenv from "dotenv";
dotenv.config();

const TENANT_ID = process.env.TENANT_ID || "00000000-0000-0000-0000-000000000000";

const MAIL_MCP_SERVER_URL =
  process.env.MAIL_MCP_SERVER_URL ||
  `https://agent365.svc.cloud.microsoft/agents/tenants/${TENANT_ID}/servers/mcp_MailTools`;

const TEAMS_MCP_SERVER_URL =
  process.env.TEAMS_MCP_SERVER_URL ||
  `https://agent365.svc.cloud.microsoft/agents/tenants/${TENANT_ID}/servers/mcp_TeamsServer`;

// Each "source" is a selectable MCP backend. They are DIFFERENT OAuth
// resources (custom API resources expose a single ".default" scope each), so
// a token acquired for one source is never valid for another — the app must
// acquire one token per selected source.
export const SOURCES = {
  mail: {
    key: "mail",
    label: "Mail",
    mcpServerUrl: MAIL_MCP_SERVER_URL,
    scopes: [`${MAIL_MCP_SERVER_URL}/.default`],
    clientName: "mcp-web-sample-mail",
    systemPrompt: `You are connected to the Microsoft "Work IQ Mail" MCP server (Microsoft Graph mail tools).
Use the available mail tools to fulfil requests about the mailbox: reading, searching, composing, replying to, sending, and managing email messages and drafts.
- Prefer calling a tool over guessing. Resolve messages to IDs first (e.g. search/list messages) before acting on a specific one.
- IDs in the mail tools are real Microsoft Graph message IDs. Never invent an ID.
- For write actions (send mail, create/send draft, reply, reply-all, update, delete) do exactly what the user asked; summarise what you did.
- When composing HTML email, set the body contentType to "HTML" (and preferHtml where supported).`,
  },
  teams: {
    key: "teams",
    label: "Teams",
    mcpServerUrl: TEAMS_MCP_SERVER_URL,
    scopes: [`${TEAMS_MCP_SERVER_URL}/.default`],
    clientName: "mcp-web-sample-teams",
    systemPrompt: `You are connected to the Microsoft Teams "Work IQ Teams" MCP server.
Use the available Teams tools to fulfil requests about Teams chats, channels, teams, members and messages.
- Prefer calling a tool over guessing. Resolve names to IDs first (e.g. list chats/teams) before acting on a specific one.
- IDs in the Teams tools are real Graph IDs. Never invent an ID.
- For write actions (post message, create/delete chat, add member) do exactly what the user asked; summarise what you did.`,
  },
};

export const SOURCE_KEYS = Object.keys(SOURCES);

/** Validate + normalize a list of requested source keys, rejecting unknown ones. */
export function parseSourceKeys(input) {
  const raw = Array.isArray(input)
    ? input
    : typeof input === "string"
      ? input.split(",")
      : [];
  const keys = raw.map((s) => String(s).trim()).filter(Boolean);
  const valid = keys.filter((k) => SOURCE_KEYS.includes(k));
  return [...new Set(valid)];
}

export const config = {
  tenantId: TENANT_ID,
  clientId: process.env.CLIENT_ID || "",
  clientSecret: process.env.CLIENT_SECRET || "",
  authority: `https://login.microsoftonline.com/${TENANT_ID}`,
  port: Number(process.env.PORT || 3002),
  redirectUri: process.env.REDIRECT_URI || "http://localhost:3002/auth/callback",
  sessionSecret: process.env.SESSION_SECRET || "dev-insecure-secret-change-me",
  llm: {
    // Azure OpenAI (Foundry)
    azureEndpoint: process.env.AZURE_OPENAI_ENDPOINT || "",
    azureApiKey: process.env.AZURE_OPENAI_API_KEY || "",
    azureDeployment: process.env.AZURE_OPENAI_DEPLOYMENT || "",
    azureApiVersion: process.env.AZURE_OPENAI_API_VERSION || "2024-10-21",
    // Entra ID (Azure AD) token scope for data-plane inference.
    azureTokenScope: "https://cognitiveservices.azure.com/.default",
    // OpenAI
    openaiApiKey: process.env.OPENAI_API_KEY || "",
    openaiModel: process.env.OPENAI_MODEL || "gpt-4o-mini",
  },
};

export function llmProvider() {
  // Azure is used when endpoint + deployment are set. Auth is by API key if
  // provided, otherwise by Entra ID (DefaultAzureCredential).
  if (config.llm.azureEndpoint && config.llm.azureDeployment) {
    return "azure";
  }
  if (config.llm.openaiApiKey) return "openai";
  return null;
}

export function assertClientId() {
  if (!config.clientId) {
    throw new Error(
      "CLIENT_ID is not set. Copy .env.example to .env and set your Entra app registration's Application (client) ID."
    );
  }
}
