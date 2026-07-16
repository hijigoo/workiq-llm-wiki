# MCP Web Sample (Mail + Teams, combined)

Unified sample that replaces the separate `mail-mcp-web-sample` and
`teams-mcp-web-sample` apps with a single web app. Checkboxes at the top of
the page let you use **Mail**, **Teams**, or **both together** — the natural
language chat, the tools sidebar, and the direct "call a tool" modal all
respect the current selection.

## Why not just merge the servers?

Mail (`mcp_MailTools`) and Teams (`mcp_TeamsServer`) are **different OAuth
resources** (each exposes its own `.default` scope), even when they live
under the same tenant/app registration. A token good for Mail is never valid
for Teams. So this app:

- Acquires a **separate access token per selected source** (`getAccessToken(session, sourceKey)`), silently reusing MSAL's cache when possible.
- Supports **incremental consent**: `/auth/login?source=mail` and `/auth/login?source=teams` are independent auth-code flows, so a user can be signed in to Mail without (yet) having consented to Teams. The checkbox row shows a small "연결" (connect) link next to any source that isn't yet authorized.
- Opens **request-scoped MCP client connections** per source (never pooled across requests) — see `withMcp`/`withMcps` in `src/mcp.js`.
- When both sources are active in one chat turn, tools from each server are exposed to the LLM with a **namespaced synthetic name** (e.g. `mail__searchMessages`, `teams__listChats`). The server keeps a per-turn registry mapping synthetic name → `{ sourceKey, originalName }` and only ever routes through that registry — it never trusts a raw tool name from the model to decide which backend to call. This avoids name collisions and keeps routing safe even if both servers happen to expose a same-named tool.
- One source failing to connect (not consented, server down, etc.) does **not** block the other — status, tool listing, and chat all use `Promise.allSettled` and report per-source errors independently.
- The combined system prompt tells the model which sources are active and warns it not to copy data from one source into a write action on another unless the user explicitly asked for that.

## Setup

```bash
cd mcp-web-sample
cp .env.example .env   # fill in CLIENT_ID (and CLIENT_SECRET if confidential client)
npm install
npm start
```

Open http://localhost:3002 (default `PORT`).

Your Entra app registration needs delegated permissions (with admin consent)
to `mcp_MailTools` and/or `mcp_TeamsServer` for whichever sources you want to
use — you can consent to just one and add the other later; the UI will show
a "연결" link for anything not yet authorized.

## Known limitations (sample, not production)

- Mixing data across sources relies on prompt instructions, not a hard
  server-side policy — do not treat this as a security boundary for
  sensitive data.
- Selecting/deselecting a source mid-conversation does not rewrite prior
  chat history; the model may still reference earlier answers derived from a
  now-deselected source.
- Tool schemas from both sources are sent to the LLM on every chat turn
  (no caching), which adds latency/token cost when both sources are active.

## Layout

```
mcp-web-sample/
  src/
    config.js   # SOURCES map (mail/teams: url, scopes, system prompt), shared app/LLM config
    auth.js     # MSAL PKCE flow, per-source login + silent token acquisition
    mcp.js      # withMcp (single source) / withMcps (multiple, for the agent loop)
    agent.js    # tool-calling loop; builds a namespaced toolset across active sources
    server.js   # Express routes: /auth/*, /api/status, /api/tools, /api/tool, /api/chat
  public/
    index.html  # header + source checkbox bar + sidebar + chat + tool modal
    app.js      # checkbox state (persisted to localStorage), status/tool rendering, chat
    styles.css
```

The original `mail-mcp-web-sample/` and `teams-mcp-web-sample/` folders are
left untouched.
