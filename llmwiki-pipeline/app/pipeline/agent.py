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
import os
from typing import Any

from .config import config, llm_provider, SOURCES
from .mcp_client import content_to_text, describe_exc, tool_input_schema, with_mcps


def _emit(progress, message: str) -> None:
    """Fire a progress callback if one was supplied; never let it break the run."""
    if progress:
        try:
            progress(message)
        except Exception:  # noqa: BLE001
            pass


def _short(value: Any, limit: int = 80) -> str:
    """Compact single-line preview of an argument/value for progress logs."""
    if isinstance(value, (dict, list)):
        try:
            s = json.dumps(value, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            s = str(value)
    else:
        s = str(value)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _arg_hint(args: dict) -> str:
    """Pick the most meaningful argument(s) so the log shows WHICH path/query a
    tool call actually used (e.g. search_paths filter, fetch entityUrls)."""
    if not isinstance(args, dict) or not args:
        return ""
    for key in (
        "filter", "functionUrl", "actionUrl", "parentUrl", "entityUrl",
        "path", "query", "question",
    ):
        val = args.get(key)
        if val:
            return f"{key}={_short(val)}"
    urls = args.get("entityUrls")
    if urls:
        if isinstance(urls, list):
            shown = ", ".join(_short(u, 60) for u in urls[:3])
            return "entityUrls=" + shown + (" …" if len(urls) > 3 else "")
        return f"entityUrls={_short(urls)}"
    parts = [f"{k}={_short(v, 40)}" for k, v in list(args.items())[:3]]
    return ", ".join(parts)


def _result_hint(text: str) -> str:
    """Summarise which paths / how many results came back (Work IQ search_paths
    returns ``{"paths": [...]}``, fetch returns ``{"results": [...]}``)."""
    if not text or text.startswith("ERROR"):
        return ""
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return ""
    if not isinstance(data, dict):
        return ""
    paths = data.get("paths")
    if isinstance(paths, list):
        names = [p.get("path") for p in paths if isinstance(p, dict) and p.get("path")]
        if not names:
            return "경로 0개"
        shown = ", ".join(names[:8])
        more = f" 외 {len(names) - 8}개" if len(names) > 8 else ""
        return f"경로 {len(names)}개: {shown}{more}"
    results = data.get("results")
    if isinstance(results, list):
        return f"결과 {len(results)}개"
    return ""


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
        if config.llm.azure_api_key.strip():
            client = AzureOpenAI(api_key=config.llm.azure_api_key.strip(), **common)
        else:
            # Keyless: Entra ID (DefaultAzureCredential -> az login / MI).
            # NOTE: an empty AZURE_OPENAI_API_KEY="" left in the environment
            # poisons the openai SDK credential check (it treats "" as a set-but-
            # invalid key and raises "Missing credentials"), so drop it before
            # building the keyless client.
            os.environ.pop("AZURE_OPENAI_API_KEY", None)
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
    progress=None,
) -> dict:
    """Run a tool-calling loop against one or more MCP servers.

    ``progress`` (optional) is a callable that receives short human-readable
    status strings as the run advances (connect -> list tools -> each tool call
    -> done); used by the web app to stream progress to the browser.

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
        if connected:
            labels = ", ".join(
                SOURCES[k].label if k in SOURCES else k for k in connected
            )
            _emit(progress, f"MCP 연결됨: {labels}. 도구 목록 로딩 중…")

        tools_by_source: dict[str, list[Any]] = {}

        # Sequential (same-task) list_tools — see mcp_client.with_mcps for why we
        # avoid spawning per-source tasks around these MCP sessions.
        for source_key in connected:
            try:
                res = await clients[source_key].list_tools()
                tools_by_source[source_key] = list(res.tools or [])
            except Exception as exc:  # noqa: BLE001
                source_errors[source_key] = describe_exc(exc)

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

        _emit(progress, f"도구 {len(tools)}개 로드됨. 데이터 수집 시작…")

        for i in range(max_iters):
            _emit(progress, f"LLM 분석 중… (단계 {i + 1}/{max_iters})")
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
                _emit(progress, "데이터 수집 완료.")
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
                    src_label = SOURCES[source_key].label if source_key in SOURCES else source_key
                    hint = _arg_hint(args)
                    suffix = f" ({hint})" if hint else ""
                    _emit(progress, f"🔧 {src_label} · {original_name} 호출 중…{suffix}")
                    client = clients.get(source_key)
                    if client is None:
                        result_text = f'ERROR: source "{source_key}" is not connected'
                    else:
                        try:
                            result = await client.call_tool(original_name, arguments=args)
                            result_text = content_to_text(result)
                            rhint = _result_hint(result_text)
                            if rhint:
                                _emit(progress, f"   ↳ {rhint}")
                        except Exception as exc:  # noqa: BLE001
                            result_text = f"ERROR calling {original_name}: {describe_exc(exc)}"

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

        _emit(progress, "도구 호출 한도에 도달했습니다.")
        return {
            "answer": "Reached the tool-call limit without a final answer. See the trace below.",
            "trace": trace,
            "source_errors": source_errors,
        }

    _emit(progress, "MCP 세션 연결 중…")
    return await with_mcps(tokens_by_source, _run)
