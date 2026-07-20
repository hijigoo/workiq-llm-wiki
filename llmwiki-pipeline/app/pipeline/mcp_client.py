"""Async MCP client helpers (Streamable HTTP transport).

Connections are request-scoped (opened, used, always closed) — never pooled
across requests — mirroring ``samples/mcp-web-sample/src/mcp.js``. The bearer
token is attached to every HTTP request via the transport headers.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import source_or_raise


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
    """Open authenticated MCP sessions for MULTIPLE sources at once, run
    ``fn(sessions, errors)``, then always close them all. One source failing to
    connect does not block the others — it is reported via the ``errors`` map.
    """
    opened: dict[str, ClientSession] = {}
    errors: dict[str, str] = {}

    async with AsyncExitStack() as stack:

        async def _open(source_key: str, token: str) -> None:
            source = source_or_raise(source_key)
            if not token:
                errors[source_key] = f"Not signed in to {source_key} (no access token)."
                return
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
                errors[source_key] = str(exc)

        await asyncio.gather(
            *(_open(k, t) for k, t in tokens_by_source.items()),
            return_exceptions=True,
        )
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
