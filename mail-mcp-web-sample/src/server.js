import express from "express";
import session from "express-session";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { config, llmProvider } from "./config.js";
import { getAuthCodeUrl, handleAuthCallback, getAccessToken, signOut } from "./auth.js";
import { listTools, callTool, contentToText } from "./mcp.js";
import { runAgent } from "./agent.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();

app.use(express.json({ limit: "1mb" }));
app.use(
  session({
    secret: config.sessionSecret,
    resave: false,
    saveUninitialized: false,
    cookie: { httpOnly: true, sameSite: "lax", maxAge: 8 * 60 * 60 * 1000 },
  })
);

app.use(express.static(path.join(__dirname, "..", "public")));

function isAuthed(req) {
  return Boolean(req.session?.homeAccountId);
}

// ---- Auth ----
app.get("/auth/login", async (req, res) => {
  try {
    const url = await getAuthCodeUrl(req.session);
    res.redirect(url);
  } catch (e) {
    res.status(500).send(`Login init failed: ${e.message}`);
  }
});

app.get("/auth/callback", async (req, res) => {
  const { code, state, error, error_description } = req.query;
  if (error) {
    return res.status(400).send(`Entra returned an error: ${error} — ${error_description || ""}`);
  }
  try {
    await handleAuthCallback(req.session, code, state);
    res.redirect("/");
  } catch (e) {
    res.status(500).send(`Auth callback failed: ${e.message}`);
  }
});

app.post("/auth/logout", async (req, res) => {
  try {
    await signOut(req.session);
  } catch {
    /* ignore */
  }
  req.session.destroy(() => res.json({ ok: true }));
});

// ---- Status ----
app.get("/api/status", async (req, res) => {
  const authed = isAuthed(req);
  const status = {
    signedIn: authed,
    user: authed ? { name: req.session.name, username: req.session.username } : null,
    llm: llmProvider(),
    mcpServerUrl: config.mcpServerUrl,
    mcpConnected: false,
    toolCount: 0,
  };
  if (authed) {
    try {
      const token = await getAccessToken(req.session);
      if (token) {
        const tools = await listTools(token);
        status.mcpConnected = true;
        status.toolCount = tools.length;
      }
    } catch (e) {
      status.mcpError = e.message;
    }
  }
  res.json(status);
});

// ---- Tools ----
app.get("/api/tools", async (req, res) => {
  if (!isAuthed(req)) return res.status(401).json({ error: "Not signed in" });
  try {
    const token = await getAccessToken(req.session);
    if (!token) return res.status(401).json({ error: "Session expired — sign in again." });
    const tools = await listTools(token);
    res.json({ tools });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post("/api/tool", async (req, res) => {
  if (!isAuthed(req)) return res.status(401).json({ error: "Not signed in" });
  const { name, args } = req.body || {};
  if (!name) return res.status(400).json({ error: "Missing tool name" });
  try {
    const token = await getAccessToken(req.session);
    if (!token) return res.status(401).json({ error: "Session expired — sign in again." });
    const result = await callTool(token, name, args || {});
    res.json({ result, text: contentToText(result) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ---- Natural-language chat (needs LLM) ----
app.post("/api/chat", async (req, res) => {
  if (!isAuthed(req)) return res.status(401).json({ error: "Not signed in" });
  const { message, history } = req.body || {};
  if (!message) return res.status(400).json({ error: "Missing message" });
  if (!llmProvider()) {
    return res.status(412).json({
      error:
        "No LLM configured. Set Azure OpenAI or OpenAI keys in .env to use natural language, or use the Tools panel to call a tool directly.",
    });
  }
  try {
    const token = await getAccessToken(req.session);
    if (!token) return res.status(401).json({ error: "Session expired — sign in again." });
    const out = await runAgent(token, message, Array.isArray(history) ? history : []);
    res.json(out);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.listen(config.port, () => {
  console.log(`\nMail MCP Web Sample running:  http://localhost:${config.port}`);
  console.log(`MCP server:  ${config.mcpServerUrl}`);
  console.log(`LLM:         ${llmProvider() || "(none — Tools panel only)"}`);
  if (!config.clientId) {
    console.log("\n⚠  CLIENT_ID is not set. Copy .env.example to .env and fill it in.\n");
  }
});
