"""Async MCP client helpers (Streamable HTTP transport).

Connections are request-scoped (opened, used, always closed) — never pooled
across requests — mirroring ``samples/mcp-web-sample/src/mcp.js``. The bearer
token is attached to every HTTP request via the transport headers.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import source_or_raise


def describe_exc(exc: BaseException, _depth: int = 0) -> str:
    """Flatten an ``ExceptionGroup`` / ``__cause__`` chain into a readable string.

    The MCP Streamable-HTTP transport wraps its read/write loops in ``anyio``
    task groups, so a failure surfaces as a ``BaseExceptionGroup`` whose ``str()``
    is the useless ``"unhandled errors in a TaskGroup (1 sub-exception)"``. This
    recurses into ``.exceptions`` (and ``__cause__``/``__context__``) so the REAL
    underlying error (e.g. an HTTP 401/403, a connection reset) is surfaced."""
    if _depth > 8:
        return f"{type(exc).__name__}: {exc}"
    subs = getattr(exc, "exceptions", None)  # ExceptionGroup / BaseExceptionGroup
    if subs:
        inner = "; ".join(describe_exc(e, _depth + 1) for e in subs)
        return inner or type(exc).__name__
    label = f"{type(exc).__name__}: {exc}".rstrip(": ").strip()
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        return f"{label} (원인: {describe_exc(cause, _depth + 1)})"
    return label


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def with_mcp(access_token: str, source_key: str, fn: Callable[[ClientSession], Awaitable[Any]]):
    """Open an authenticated MCP session for ONE source, run ``fn(session)``,
    then always close it."""
    if not access_token:
        raise RuntimeError(f"Not signed in to {source_key} (no access token).")
    source = source_or_raise(source_key)

    async with streamablehttp_client(
        source.mcp_server_url, headers=_auth_headers(access_token)
    ) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


async def with_mcps(
    tokens_by_source: dict[str, str],
    fn: Callable[[dict[str, ClientSession], dict[str, str]], Awaitable[Any]],
):
    """Open authenticated MCP sessions for MULTIPLE sources, run
    ``fn(sessions, errors)``, then always close them all. One source failing to
    connect does not block the others — it is reported via the ``errors`` map.

    Sessions are opened AND closed in this single task, on purpose: the MCP
    transports use ``anyio`` cancel scopes, which must be entered and exited in
    the same task. Opening them in separate tasks (e.g. via ``asyncio.gather``)
    while unwinding the shared ``AsyncExitStack`` here raises "Attempted to exit
    cancel scope in a different task than it was entered in". With only a couple
    of sources the sequential connect is cheap; the slow part is the LLM loop.
    """
    opened: dict[str, ClientSession] = {}
    errors: dict[str, str] = {}

    async with AsyncExitStack() as stack:
        for source_key, token in tokens_by_source.items():
            try:
                source = source_or_raise(source_key)
            except Exception as exc:  # noqa: BLE001
                errors[source_key] = str(exc)
                continue
            if not token:
                errors[source_key] = f"Not signed in to {source_key} (no access token)."
                continue
            try:
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(
                        source.mcp_server_url, headers=_auth_headers(token)
                    )
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                opened[source_key] = session
            except Exception as exc:  # noqa: BLE001 - report per-source, keep going
                errors[source_key] = describe_exc(exc)
        return await fn(opened, errors)


async def list_tools(access_token: str, source_key: str) -> list[Any]:
    async def _fn(session: ClientSession):
        res = await session.list_tools()
        return list(res.tools or [])

    return await with_mcp(access_token, source_key, _fn)


async def call_tool(access_token: str, source_key: str, name: str, args: dict | None = None):
    async def _fn(session: ClientSession):
        return await session.call_tool(name, arguments=args or {})

    return await with_mcp(access_token, source_key, _fn)


def content_to_text(result: Any) -> str:
    """Flatten an MCP tool result's ``content`` array into a readable string."""
    if result is None:
        return ""

    content = getattr(result, "content", None) or []
    is_error = bool(getattr(result, "isError", False))

    def _block_to_text(block: Any) -> str:
        btype = getattr(block, "type", None)
        if btype == "text":
            return getattr(block, "text", "")
        # Non-text block: dump whatever structured payload it carries.
        try:
            if hasattr(block, "model_dump"):
                data = block.model_dump()
            else:
                data = block
            import json

            return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n```"
        except Exception:  # noqa: BLE001
            return str(block)

    parts = [_block_to_text(b) for b in content]
    text = "\n".join(parts)
    return f"ERROR: {text}" if is_error else text


def tool_input_schema(tool: Any) -> dict:
    """Return an MCP tool's JSON input schema in a defensive way."""
    schema = getattr(tool, "inputSchema", None)
    if not schema:
        return {"type": "object", "properties": {}}
    if hasattr(schema, "model_dump"):
        return schema.model_dump()
    return schema
