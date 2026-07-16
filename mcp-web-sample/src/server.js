import express from "express";
import session from "express-session";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { config, llmProvider, SOURCES, SOURCE_KEYS, parseSourceKeys } from "./config.js";
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

// Requested sources come from query (GET) or body (POST); default to ALL
// known sources for status/tools, but chat requires an explicit non-empty
// selection (checkbox state) from the client.
function requestedSources(req, { fallbackAll } = {}) {
  const raw = req.method === "GET" ? req.query.sources : req.body?.sources;
  const keys = parseSourceKeys(raw);
  if (keys.length === 0 && fallbackAll) return [...SOURCE_KEYS];
  return keys;
}

// ---- Auth ----
app.get("/auth/login", async (req, res) => {
  const sourceKey = String(req.query.source || "");
  if (!SOURCES[sourceKey]) {
    return res.status(400).send(`Missing/unknown ?source=. Valid values: ${SOURCE_KEYS.join(", ")}`);
  }
  try {
    const url = await getAuthCodeUrl(req.session, sourceKey);
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
// Reports per-source connectivity independently (Promise.allSettled) so one
// source being down/not-consented doesn't hide the other's working state.
app.get("/api/status", async (req, res) => {
  const authed = isAuthed(req);
  const sources = {};

  await Promise.allSettled(
    SOURCE_KEYS.map(async (key) => {
      sources[key] = {
        label: SOURCES[key].label,
        signedIn: false,
        connected: false,
        toolCount: 0,
      };
      if (!authed) return;
      try {
        const token = await getAccessToken(req.session, key);
        sources[key].signedIn = Boolean(token);
        if (token) {
          const tools = await listTools(token, key);
          sources[key].connected = true;
          sources[key].toolCount = tools.length;
        }
      } catch (e) {
        sources[key].error = e.message;
      }
    })
  );

  res.json({
    signedIn: authed,
    user: authed ? { name: req.session.name, username: req.session.username } : null,
    llm: llmProvider(),
    sources,
  });
});

// ---- Tools ----
app.get("/api/tools", async (req, res) => {
  if (!isAuthed(req)) return res.status(401).json({ error: "Not signed in" });
  const keys = requestedSources(req, { fallbackAll: true });
  const tools = [];
  const errors = {};

  await Promise.allSettled(
    keys.map(async (key) => {
      try {
        const token = await getAccessToken(req.session, key);
        if (!token) {
          errors[key] = "Not connected — sign in to this source first.";
          return;
        }
        const sourceTools = await listTools(token, key);
        sourceTools.forEach((t) => tools.push({ ...t, source: key, sourceLabel: SOURCES[key].label }));
      } catch (e) {
        errors[key] = e.message;
      }
    })
  );

  res.json({ tools, errors });
});

app.post("/api/tool", async (req, res) => {
  if (!isAuthed(req)) return res.status(401).json({ error: "Not signed in" });
  const { source, name, args } = req.body || {};
  if (!SOURCES[source]) {
    return res.status(400).json({ error: `Missing/unknown source. Valid values: ${SOURCE_KEYS.join(", ")}` });
  }
  if (!name) return res.status(400).json({ error: "Missing tool name" });
  try {
    const token = await getAccessToken(req.session, source);
    if (!token) return res.status(401).json({ error: `Not connected to ${source} — sign in to this source first.` });
    const result = await callTool(token, source, name, args || {});
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

  const keys = requestedSources(req, { fallbackAll: false });
  if (keys.length === 0) {
    return res.status(400).json({
      error: "No source selected. Check at least one of Mail / Teams above the chat before sending.",
    });
  }
  if (!llmProvider()) {
    return res.status(412).json({
      error:
        "No LLM configured. Set Azure OpenAI or OpenAI keys in .env to use natural language, or use the Tools panel to call a tool directly.",
    });
  }

  try {
    const tokensBySource = {};
    for (const key of keys) {
      const token = await getAccessToken(req.session, key);
      if (token) tokensBySource[key] = token;
    }
    if (Object.keys(tokensBySource).length === 0) {
      return res.status(401).json({
        error: "Not connected to any of the selected sources. Sign in to at least one of them first.",
      });
    }
    const out = await runAgent(tokensBySource, message, Array.isArray(history) ? history : []);
    res.json(out);
  } catch (e) {
    if (e.code === "LLM_NOT_CONFIGURED") {
      return res.status(412).json({ error: "No LLM configured." });
    }
    res.status(500).json({ error: e.message });
  }
});

app.listen(config.port, () => {
  console.log(`\nMCP Web Sample running:  http://localhost:${config.port}`);
  SOURCE_KEYS.forEach((k) => console.log(`  ${SOURCES[k].label} MCP: ${SOURCES[k].mcpServerUrl}`));
  console.log(`LLM:         ${llmProvider() || "(none — Tools panel only)"}`);
  if (!config.clientId) {
    console.log("\n⚠  CLIENT_ID is not set. Copy .env.example to .env and fill it in.\n");
  }
});
