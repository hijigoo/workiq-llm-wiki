"""LLM tool-calling agent across one or more MCP sources.

Ported from ``samples/mcp-web-sample/src/agent.js``. Each MCP tool is exposed
to the model under a synthetic, source-namespaced name (e.g. ``mail__...``,
``teams__...``); a per-turn registry maps that name back to
``(source_key, original_name)`` so routing never trusts a raw model-supplied
name.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .config import config, llm_provider, SOURCES
from .mcp_client import content_to_text, tool_input_schema, with_mcps


def make_openai() -> dict | None:
    """Return ``{"client", "model"}`` for the configured provider, or None."""
    provider = llm_provider()
    if provider == "azure":
        from openai import AzureOpenAI

        common = dict(
            azure_endpoint=config.llm.azure_endpoint,
            azure_deployment=config.llm.azure_deployment,
            api_version=config.llm.azure_api_version,
        )
        if config.llm.azure_api_key:
            client = AzureOpenAI(api_key=config.llm.azure_api_key, **common)
        else:
            # Keyless: Entra ID (DefaultAzureCredential -> az login / MI).
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), config.llm.azure_token_scope
            )
            client = AzureOpenAI(azure_ad_token_provider=token_provider, **common)
        return {"client": client, "model": config.llm.azure_deployment}

    if provider == "openai":
        from openai import OpenAI

        return {"client": OpenAI(api_key=config.llm.openai_api_key), "model": config.llm.openai_model}

    return None


def build_toolset(tools_by_source: dict[str, list[Any]]) -> tuple[list[dict], dict[str, dict]]:
    """Build the OpenAI tool list + a registry mapping synthetic name ->
    ``{source_key, original_name}``."""
    registry: dict[str, dict] = {}
    tools: list[dict] = []
    seen: dict[str, int] = {}

    for source_key, mcp_tools in tools_by_source.items():
        for t in mcp_tools:
            base = f"{source_key}__{t.name}"[:60]
            unique = base
            count = seen.get(base, 0)
            if count > 0:
                unique = f"{base}_{count}"[:64]
            seen[base] = count + 1

            registry[unique] = {"source_key": source_key, "original_name": t.name}
            label = SOURCES[source_key].label if source_key in SOURCES else source_key
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": unique,
                        "description": f"[{label}] {t.description or t.name}",
                        "parameters": tool_input_schema(t),
                    },
                }
            )
    return tools, registry


def build_system_prompt(source_keys: list[str]) -> str:
    intros = "\n\n".join(
        f"--- {SOURCES[k].label} tools ---\n{SOURCES[k].system_prompt}"
        for k in source_keys
        if k in SOURCES
    )
    active = ", ".join(SOURCES[k].label if k in SOURCES else k for k in source_keys) or "(none)"
    return (
        'You are a helpful assistant connected to one or more Microsoft "Work IQ" MCP servers.\n'
        f"Active sources for this conversation: {active}.\n"
        'Every tool name is prefixed with its source (e.g. "mail__..." or "teams__...") — '
        "only call tools that belong to a source relevant to the request.\n"
        "Be careful about mixing data across sources: do not copy or forward content from one "
        "source (e.g. mail) into a write action on another source (e.g. posting to Teams) unless "
        "the user explicitly asked you to do that.\n"
        "Answer in the user's language. Be concise. Never invent IDs — resolve names to IDs via a "
        "list/search tool first.\n\n"
        f"{intros}"
    )


async def run_agent(
    tokens_by_source: dict[str, str],
    user_message: str,
    history: list[dict] | None = None,
    max_iters: int = 8,
) -> dict:
    """Run a tool-calling loop against one or more MCP servers.

    Returns ``{"answer", "trace", "source_errors"}``.
    """
    oa = make_openai()
    if oa is None:
        raise RuntimeError("LLM_NOT_CONFIGURED")

    source_keys = list(tokens_by_source.keys())
    if not source_keys:
        raise RuntimeError("NO_SOURCE_SELECTED")

    history = history or []

    async def _run(clients: dict, connect_errors: dict) -> dict:
        source_errors = dict(connect_errors)
        connected = list(clients.keys())

        tools_by_source: dict[str, list[Any]] = {}

        async def _list(source_key: str) -> None:
            try:
                res = await clients[source_key].list_tools()
                tools_by_source[source_key] = list(res.tools or [])
            except Exception as exc:  # noqa: BLE001
                source_errors[source_key] = str(exc)

        await asyncio.gather(*(_list(k) for k in connected), return_exceptions=True)

        tools, registry = build_toolset(tools_by_source)
        messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(source_keys)},
            *history,
            {"role": "user", "content": user_message},
        ]
        trace: list[dict] = []

        if not tools:
            return {
                "answer": "선택된 소스에서 사용할 수 있는 도구가 없습니다. 연결 상태를 확인하세요.",
                "trace": trace,
                "source_errors": source_errors,
            }

        for _ in range(max_iters):
            completion = await asyncio.to_thread(
                oa["client"].chat.completions.create,
                model=oa["model"],
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
            )
            msg = completion.choices[0].message

            assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            if not msg.tool_calls:
                return {"answer": msg.content or "(no content)", "trace": trace, "source_errors": source_errors}

            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments) if call.function.arguments else {}
                except Exception:  # noqa: BLE001
                    args = {}

                entry = registry.get(call.function.name)
                if entry is None:
                    result_text = f'ERROR: unknown tool "{call.function.name}"'
                else:
                    source_key = entry["source_key"]
                    original_name = entry["original_name"]
                    client = clients.get(source_key)
                    if client is None:
                        result_text = f'ERROR: source "{source_key}" is not connected'
                    else:
                        try:
                            result = await client.call_tool(original_name, arguments=args)
                            result_text = content_to_text(result)
                        except Exception as exc:  # noqa: BLE001
                            result_text = f"ERROR calling {original_name}: {exc}"

                trace.append(
                    {
                        "tool": entry["original_name"] if entry else call.function.name,
                        "source": entry["source_key"] if entry else None,
                        "args": args,
                        "result": result_text,
                    }
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result_text[:8000]}
                )

        return {
            "answer": "Reached the tool-call limit without a final answer. See the trace below.",
            "trace": trace,
            "source_errors": source_errors,
        }

    return await with_mcps(tokens_by_source, _run)
