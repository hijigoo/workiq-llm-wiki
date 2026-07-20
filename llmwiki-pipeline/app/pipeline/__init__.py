"""LLM Wiki pipeline — shared package.

Extracts technical / know-how knowledge from the Microsoft Work IQ Teams and
Mail MCP servers via natural language, turns it into review-ready Markdown wiki
pages, and commits approved pages to this repository.

Public surface:
    config      — settings, SOURCES, llm_provider()
    auth        — Entra ID tokens (device-code / client-credentials)
    mcp_client  — async MCP session helpers
    agent       — LLM tool-calling loop across sources
    extract     — NL query -> gathered knowledge
    generate    — gathered knowledge -> markdown doc
    wiki        — save / list / read + git commit
    pipeline    — end-to-end orchestration (run_pipeline)
"""

from . import agent, auth, config, extract, generate, mcp_client, pipeline, wiki

__all__ = [
    "agent",
    "auth",
    "config",
    "extract",
    "generate",
    "mcp_client",
    "pipeline",
    "wiki",
]
