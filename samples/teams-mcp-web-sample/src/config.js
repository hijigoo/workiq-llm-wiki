import dotenv from "dotenv";
dotenv.config();

const TENANT_ID = process.env.TENANT_ID || "00000000-0000-0000-0000-000000000000";

const MCP_SERVER_URL =
  process.env.MCP_SERVER_URL ||
  `https://agent365.svc.cloud.microsoft/agents/tenants/${TENANT_ID}/servers/mcp_TeamsServer`;

export const config = {
  tenantId: TENANT_ID,
  clientId: process.env.CLIENT_ID || "",
  clientSecret: process.env.CLIENT_SECRET || "",
  authority: `https://login.microsoftonline.com/${TENANT_ID}`,
  mcpServerUrl: MCP_SERVER_URL,
  // Custom API resources expose a single ".default" scope in their metadata.
  scopes: [`${MCP_SERVER_URL}/.default`],
  port: Number(process.env.PORT || 3000),
  redirectUri: process.env.REDIRECT_URI || "http://localhost:3000/auth/callback",
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
