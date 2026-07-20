"""Step 1 of the pipeline: natural-language extraction.

Given a plain-language description of *what* to extract and a date range, run
the tool-calling agent against the selected MCP sources (Teams / Mail) to
gather only the relevant technical / know-how items. The agent's final answer
plus its tool-call trace form the raw material handed to ``generate``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .agent import run_agent
from .config import SOURCES


def default_date_range(days: int = 1) -> tuple[str, str]:
    """Return ``(start, end)`` ISO dates covering the last ``days`` days
    (inclusive of today). ``days=1`` => yesterday..today."""
    end = date.today()
    start = end - timedelta(days=max(days, 0))
    return start.isoformat(), end.isoformat()


def _coerce_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return str(value)


def build_extraction_prompt(query: str, start: str, end: str, source_keys: list[str]) -> str:
    labels = ", ".join(SOURCES[k].label for k in source_keys if k in SOURCES)
    return (
        "You are building a knowledge-wiki extraction. Collect messages and emails that contain "
        "reusable technical knowledge or know-how (how-tos, decisions, troubleshooting, tips, "
        "configurations, lessons learned) matching this topic:\n\n"
        f"TOPIC / REQUEST:\n{query}\n\n"
        f"DATE RANGE (inclusive): {start} .. {end}\n"
        f"SOURCES TO SEARCH: {labels}\n\n"
        "Instructions:\n"
        "1. Use search/list tools to find candidate items within the date range. Prefer date-"
        "   filtered searches where the tools support it.\n"
        "2. Keep ONLY items relevant to the topic and that carry actual technical knowledge; "
        "   drop scheduling chatter, greetings, and pure logistics.\n"
        "3. For every kept item, report: source (Mail/Teams), author/sender, timestamp, a title/"
        "   subject, the real item ID, and a faithful summary of the useful content (quote key "
        "   commands/snippets verbatim).\n"
        "4. Do NOT invent data. If nothing relevant is found, say so explicitly.\n\n"
        "Return a structured list of the relevant items grouped by source. This is source "
        "material for a wiki page, so be thorough and precise, not conversational."
    )


async def extract_knowledge(
    tokens_by_source: dict[str, str],
    query: str,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """Run the extraction agent and return the gathered material.

    Returns ``{"query", "start", "end", "sources", "answer", "trace",
    "source_errors"}``.
    """
    if start is None or end is None:
        d_start, d_end = default_date_range()
        start = start or d_start
        end = end or d_end
    start, end = _coerce_date(start), _coerce_date(end)

    source_keys = list(tokens_by_source.keys())
    prompt = build_extraction_prompt(query, start, end, source_keys)
    result = await run_agent(tokens_by_source, prompt)

    return {
        "query": query,
        "start": start,
        "end": end,
        "sources": source_keys,
        "answer": result["answer"],
        "trace": result["trace"],
        "source_errors": result["source_errors"],
    }
