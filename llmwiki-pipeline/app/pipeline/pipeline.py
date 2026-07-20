"""Full pipeline orchestration: extract -> generate (draft).

``run_pipeline`` gathers relevant knowledge from the selected MCP sources for a
natural-language query + date range and produces a draft markdown document. It
does NOT save or commit — the review/edit/commit step is driven by the app (or
notebook 04) via the ``wiki`` module, so a human always reviews before the doc
lands in the repo.
"""

from __future__ import annotations

from .auth import ensure_access_token, tokens_for_sources
from .config import SOURCE_KEYS, parse_source_keys
from .extract import default_date_range, extract_knowledge
from .generate import to_markdown


def resolve_sources(sources=None) -> list[str]:
    if not sources:
        return list(SOURCE_KEYS)
    keys = parse_source_keys(sources)
    return keys or list(SOURCE_KEYS)


def gather_tokens(source_keys: list[str], ensure_login: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(tokens_by_source, errors)``. When ``ensure_login`` is True,
    missing sources trigger an interactive (device-code) login where supported.
    """
    if ensure_login:
        tokens: dict[str, str] = {}
        errors: dict[str, str] = {}
        for key in source_keys:
            try:
                tokens[key] = ensure_access_token(key)
            except Exception as exc:  # noqa: BLE001
                errors[key] = str(exc)
        return tokens, errors

    tokens = tokens_for_sources(source_keys)
    errors = {
        k: "Not signed in — run the setup notebook / terminal login for this source first."
        for k in source_keys
        if k not in tokens
    }
    return tokens, errors


async def run_pipeline(
    query: str,
    start: str | None = None,
    end: str | None = None,
    sources=None,
    ensure_login: bool = False,
) -> dict:
    """Run extract -> generate and return a draft.

    Returns ``{"query", "start", "end", "sources", "extract", "doc",
    "token_errors", "source_errors"}``. ``doc`` is None when no LLM/source is
    available.
    """
    source_keys = resolve_sources(sources)
    if start is None or end is None:
        d_start, d_end = default_date_range()
        start = start or d_start
        end = end or d_end

    tokens, token_errors = gather_tokens(source_keys, ensure_login=ensure_login)

    if not tokens:
        return {
            "query": query,
            "start": start,
            "end": end,
            "sources": source_keys,
            "extract": None,
            "doc": None,
            "token_errors": token_errors,
            "source_errors": {},
        }

    extract_result = await extract_knowledge(tokens, query, start=start, end=end)
    doc = await to_markdown(extract_result)

    return {
        "query": query,
        "start": start,
        "end": end,
        "sources": list(tokens.keys()),
        "extract": extract_result,
        "doc": doc,
        "token_errors": token_errors,
        "source_errors": extract_result.get("source_errors", {}),
    }
