"""FastAPI app for the LLM Wiki pipeline.

Flow the UI drives:
    1. Enter a natural-language topic + date range, pick sources (Mail/Teams).
    2. POST /api/run  -> extract from MCP + generate a draft markdown doc.
    3. Review / edit the draft in the browser.
    4. POST /api/commit -> save to the wiki dir + git commit into this repo.

Auth: the app uses tokens from the shared MSAL cache. Sign in once via
notebook/01_setup_mcp.ipynb (device code) or set AUTH_MODE=client_credentials.
Run:  cd app && uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the sibling `pipeline` package importable when run from anywhere.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from pipeline import wiki  # noqa: E402
from pipeline.auth import get_access_token  # noqa: E402
from pipeline.config import SOURCES, SOURCE_KEYS, config, llm_provider  # noqa: E402
from pipeline.pipeline import resolve_sources, run_pipeline  # noqa: E402

app = FastAPI(title="LLM Wiki Pipeline")

STATIC_DIR = APP_DIR / "static"


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
def api_status():
    sources = {}
    for key in SOURCE_KEYS:
        info = {"label": SOURCES[key].label, "signedIn": False}
        try:
            token = get_access_token(key)
            info["signedIn"] = bool(token)
        except Exception as exc:  # noqa: BLE001
            info["error"] = str(exc)
        sources[key] = info
    return {
        "llm": llm_provider(),
        "authMode": config.auth_mode,
        "sources": sources,
    }


@app.post("/api/run")
async def api_run(req: RunRequest):
    if not req.query or not req.query.strip():
        return JSONResponse(status_code=400, content={"error": "질의(query)를 입력하세요."})
    if not llm_provider():
        return JSONResponse(
            status_code=412,
            content={"error": "LLM이 설정되지 않았습니다. .env에 Azure OpenAI 또는 OpenAI 키를 설정하세요."},
        )
    try:
        result = await run_pipeline(
            req.query, start=req.start, end=req.end, sources=req.sources
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(exc)})

    doc = result.get("doc")
    return {
        "query": result["query"],
        "start": result["start"],
        "end": result["end"],
        "sources": result["sources"],
        "tokenErrors": result.get("token_errors", {}),
        "sourceErrors": result.get("source_errors", {}),
        "doc": None
        if doc is None
        else {"title": doc["title"], "slug": doc["slug"], "markdown": doc["markdown"]},
        "extractAnswer": (result.get("extract") or {}).get("answer") if result.get("extract") else None,
    }


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
