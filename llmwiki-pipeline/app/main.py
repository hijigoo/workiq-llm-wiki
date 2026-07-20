"""FastAPI app for the LLM Wiki pipeline.

Flow the UI drives:
    1. Sign in (browser redirect) via the header 로그인 button — Authorization
       Code flow, per source (Mail / Teams).
    2. Enter a natural-language topic + date range, pick sources.
    3. POST /api/run  -> extract from MCP + generate a draft markdown doc.
    4. Review / edit the draft in the browser.
    5. POST /api/commit -> save to the wiki dir + git commit into this repo.

Auth: the app is a confidential client (uses CLIENT_SECRET) and signs each user
in interactively; tokens are held per user session. The LLM (Foundry) auth is
separate (az login / DefaultAzureCredential when AZURE_OPENAI_API_KEY is empty).
Run:  cd app && uvicorn main:app --reload --port 8000  (open http://localhost:8000)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

# Make the sibling `pipeline` package importable when run from anywhere.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import (  # noqa: E402
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from pipeline import wiki  # noqa: E402
from pipeline.auth import (  # noqa: E402
    build_auth_flow,
    redeem_auth_flow,
    remove_account,
    resolve_account,
    token_for_account,
)
from pipeline.config import SOURCES, SOURCE_KEYS, config, llm_provider  # noqa: E402
from pipeline.mcp_client import (  # noqa: E402
    call_tool,
    content_to_text,
    list_tools,
    tool_input_schema,
)
from pipeline.pipeline import resolve_sources, run_pipeline  # noqa: E402

app = FastAPI(title="LLM Wiki Pipeline")

# Per-user server session (signed cookie). Holds only the signed-in account's
# home_account_id + display name; the access/refresh tokens stay in the MSAL
# token cache, never in the cookie.
app.add_middleware(
    SessionMiddleware,
    secret_key=config.session_secret,
    same_site="lax",
    https_only=False,
    max_age=8 * 60 * 60,
)

STATIC_DIR = APP_DIR / "static"


def _session_token(request: Request, source: str) -> Optional[str]:
    """Silently get an access token for ``source`` for the session's account."""
    hid = request.session.get("home_account_id")
    if not hid:
        return None
    try:
        return token_for_account(hid, source)
    except Exception:  # noqa: BLE001
        return None


def _session_status(request: Request) -> dict:
    """signedIn + user + per-source connectivity for the current session."""
    hid = request.session.get("home_account_id")
    signed_in = bool(hid)
    sources = {}
    for key in SOURCE_KEYS:
        info = {"label": SOURCES[key].label, "signedIn": False}
        if signed_in:
            try:
                info["signedIn"] = bool(token_for_account(hid, key))
            except Exception as exc:  # noqa: BLE001
                info["error"] = str(exc)
        sources[key] = info
    return {
        "signedIn": signed_in,
        "user": {
            "name": request.session.get("name"),
            "username": request.session.get("username"),
        }
        if signed_in
        else None,
        "sources": sources,
    }


class RunRequest(BaseModel):
    query: str
    start: str | None = None
    end: str | None = None
    sources: list[str] | None = None


class CommitRequest(BaseModel):
    markdown: str
    slug: str = "wiki-doc"
    filename: str | None = None
    message: str | None = None


@app.get("/api/status")
def api_status(request: Request):
    return {
        "llm": llm_provider(),
        "authMode": "user-login (secret)" if config.client_secret else "user-login (pkce)",
        **_session_status(request),
    }


# ---- Interactive login (Authorization Code flow, per source) ----
@app.get("/auth/login")
def auth_login(request: Request, source: str = "mail"):
    """Redirect the browser to Entra to sign in for one source. Mail/Teams are
    different OAuth resources, so ?source= picks which one to (incrementally)
    consent + connect."""
    if source not in SOURCE_KEYS:
        return JSONResponse(status_code=400, content={"error": f"알 수 없는 소스: {source}"})
    try:
        flow = build_auth_flow(source)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(
            f"<p>로그인 시작 실패: {exc}</p><p><a href='/'>돌아가기</a></p>",
            status_code=500,
        )
    request.session["auth_flow"] = flow
    return RedirectResponse(flow["auth_uri"], status_code=302)


@app.get("/auth/callback")
def auth_callback(request: Request):
    """Entra redirects here with ?code&state. Exchange for tokens, remember the
    account in the session, then bounce back to the app."""
    params = dict(request.query_params)
    if params.get("error"):
        return HTMLResponse(
            f"<p>Entra 오류: {params.get('error')} — {params.get('error_description', '')}</p>"
            f"<p><a href='/'>돌아가기</a></p>",
            status_code=400,
        )
    flow = request.session.pop("auth_flow", None)
    if not flow:
        return HTMLResponse(
            "<p>진행 중인 로그인이 없습니다.</p><p><a href='/'>돌아가기</a></p>",
            status_code=400,
        )
    try:
        result = redeem_auth_flow(flow, params)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(
            f"<p>로그인 교환 실패: {exc}</p><p><a href='/'>돌아가기</a></p>",
            status_code=500,
        )
    if "access_token" not in result:
        detail = result.get("error_description") or result.get("error") or result
        return HTMLResponse(
            f"<p>로그인 실패: {detail}</p><p><a href='/'>돌아가기</a></p>",
            status_code=400,
        )
    claims = result.get("id_token_claims", {}) or {}
    account = resolve_account(result)
    if account:
        request.session["home_account_id"] = account.get("home_account_id")
        request.session["username"] = account.get("username") or claims.get(
            "preferred_username"
        )
    request.session["name"] = claims.get("name") or request.session.get("username")
    return RedirectResponse("/", status_code=302)


@app.post("/api/logout")
def api_logout(request: Request):
    """Sign the current user out: drop the account from the token cache and clear
    the session."""
    hid = request.session.get("home_account_id")
    removed: list[str] = []
    if hid:
        username = request.session.get("username")
        try:
            remove_account(hid)
            if username:
                removed.append(username)
        except Exception:  # noqa: BLE001
            pass
    request.session.clear()
    return {"ok": True, "removed": removed, **_session_status(request)}


@app.get("/api/tools/{source}")
async def api_tools(source: str, request: Request):
    """List the MCP tools callable on one source, with their JSON input schema."""
    if source not in SOURCE_KEYS:
        return JSONResponse(status_code=404, content={"error": f"알 수 없는 소스: {source}"})
    token = _session_token(request, source)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"error": f"{SOURCES[source].label}에 로그인되어 있지 않습니다."},
        )
    try:
        tools = await list_tools(token, source)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(exc)})
    return {
        "source": source,
        "label": SOURCES[source].label,
        "tools": [
            {
                "name": t.name,
                "description": getattr(t, "description", "") or "",
                "inputSchema": tool_input_schema(t),
            }
            for t in tools
        ],
    }


class ToolCallRequest(BaseModel):
    source: str
    tool: str
    args: dict | None = None


@app.post("/api/tools/call")
async def api_tools_call(req: ToolCallRequest, request: Request):
    """Invoke one MCP tool with the given arguments and return its readable result."""
    if req.source not in SOURCE_KEYS:
        return JSONResponse(status_code=404, content={"error": f"알 수 없는 소스: {req.source}"})
    if not req.tool or not req.tool.strip():
        return JSONResponse(status_code=400, content={"error": "tool 이름이 필요합니다."})
    token = _session_token(request, req.source)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"error": f"{SOURCES[req.source].label}에 로그인되어 있지 않습니다."},
        )
    try:
        result = await call_tool(token, req.source, req.tool, req.args or {})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": str(exc)})
    return {
        "source": req.source,
        "tool": req.tool,
        "isError": bool(getattr(result, "isError", False)),
        "text": content_to_text(result),
    }


@app.post("/api/run")
async def api_run(req: RunRequest, request: Request):
    if not req.query or not req.query.strip():
        return JSONResponse(status_code=400, content={"error": "질의(query)를 입력하세요."})
    if not llm_provider():
        return JSONResponse(
            status_code=412,
            content={"error": "LLM이 설정되지 않았습니다. .env에 Azure OpenAI 또는 OpenAI 키를 설정하세요."},
        )
    source_keys = resolve_sources(req.sources)
    hid = request.session.get("home_account_id")
    tokens: dict[str, str] = {}
    if hid:
        for key in source_keys:
            tok = _session_token(request, key)
            if tok:
                tokens[key] = tok

    # Stream progress to the browser as Server-Sent Events. The pipeline runs in
    # a worker task and pushes {type:progress|result|error} events onto a queue;
    # the generator drains the queue until the sentinel (None).
    queue: asyncio.Queue = asyncio.Queue()

    def progress(message: str) -> None:
        queue.put_nowait({"type": "progress", "message": message})

    async def worker() -> None:
        try:
            result = await run_pipeline(
                req.query,
                start=req.start,
                end=req.end,
                sources=req.sources,
                tokens=tokens,
                progress=progress,
            )
            doc = result.get("doc")
            queue.put_nowait(
                {
                    "type": "result",
                    "query": result["query"],
                    "start": result["start"],
                    "end": result["end"],
                    "sources": result["sources"],
                    "tokenErrors": result.get("token_errors", {}),
                    "sourceErrors": result.get("source_errors", {}),
                    "doc": None
                    if doc is None
                    else {
                        "title": doc["title"],
                        "slug": doc["slug"],
                        "markdown": doc["markdown"],
                    },
                    "extractAnswer": (result.get("extract") or {}).get("answer")
                    if result.get("extract")
                    else None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            queue.put_nowait({"type": "error", "error": str(exc)})
        finally:
            queue.put_nowait(None)

    async def event_stream():
        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/commit")
def api_commit(req: CommitRequest):
    if not req.markdown or not req.markdown.strip():
        return JSONResponse(status_code=400, content={"error": "빈 문서는 커밋할 수 없습니다."})
    try:
        out = wiki.save_and_commit(
            req.markdown, req.slug, message=req.message, filename=req.filename
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return out


@app.get("/api/docs")
def api_docs():
    return {"docs": wiki.list_docs()}


@app.get("/api/docs/{filename}")
def api_doc(filename: str):
    try:
        return {"filename": filename, "markdown": wiki.read_doc(filename)}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=404, content={"error": str(exc)})


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# Static assets (app.js, styles.css). Mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
