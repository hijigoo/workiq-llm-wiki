"""Configuration hub for the LLM Wiki pipeline.

Loads `.env`, exposes the two selectable MCP sources (Mail / Teams), the LLM
settings, auth mode and wiki output directory. Mirrors the structure of the
Node `samples/mcp-web-sample/src/config.js` but in Python.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = llmwiki-pipeline/ (this file is app/pipeline/config.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load .env from the project root (if present).
load_dotenv(PROJECT_ROOT / ".env")

TENANT_ID = os.environ.get("TENANT_ID", "00000000-0000-0000-0000-000000000000")

MAIL_MCP_SERVER_URL = os.environ.get(
    "MAIL_MCP_SERVER_URL",
    f"https://agent365.svc.cloud.microsoft/agents/tenants/{TENANT_ID}/servers/mcp_MailTools",
)
TEAMS_MCP_SERVER_URL = os.environ.get(
    "TEAMS_MCP_SERVER_URL",
    f"https://agent365.svc.cloud.microsoft/agents/tenants/{TENANT_ID}/servers/mcp_TeamsServer",
)


@dataclass(frozen=True)
class Source:
    """A selectable MCP backend. Mail and Teams are DIFFERENT OAuth resources
    (each exposes its own ``.default`` scope), so a token acquired for one is
    never valid for the other — one token is acquired per selected source."""

    key: str
    label: str
    mcp_server_url: str
    scopes: list[str]
    client_name: str
    system_prompt: str


MAIL_SYSTEM_PROMPT = """You are connected to the Microsoft "Work IQ Mail" MCP server (Microsoft Graph mail tools).
Use the available mail tools to fulfil requests about the mailbox: reading, searching, composing, replying to, sending, and managing email messages and drafts.
- Prefer calling a tool over guessing. Resolve messages to IDs first (e.g. search/list messages) before acting on a specific one.
- IDs in the mail tools are real Microsoft Graph message IDs. Never invent an ID.
- For write actions (send mail, create/send draft, reply, reply-all, update, delete) do exactly what the user asked; summarise what you did.
- When composing HTML email, set the body contentType to "HTML" (and preferHtml where supported)."""

TEAMS_SYSTEM_PROMPT = """You are connected to the Microsoft Teams "Work IQ Teams" MCP server.
Use the available Teams tools to fulfil requests about Teams chats, channels, teams, members and messages.
- Prefer calling a tool over guessing. Resolve names to IDs first (e.g. list chats/teams) before acting on a specific one.
- IDs in the Teams tools are real Graph IDs. Never invent an ID.
- For write actions (post message, create/delete chat, add member) do exactly what the user asked; summarise what you did."""


SOURCES: dict[str, Source] = {
    "mail": Source(
        key="mail",
        label="Mail",
        mcp_server_url=MAIL_MCP_SERVER_URL,
        scopes=[f"{MAIL_MCP_SERVER_URL}/.default"],
        client_name="llmwiki-pipeline-mail",
        system_prompt=MAIL_SYSTEM_PROMPT,
    ),
    "teams": Source(
        key="teams",
        label="Teams",
        mcp_server_url=TEAMS_MCP_SERVER_URL,
        scopes=[f"{TEAMS_MCP_SERVER_URL}/.default"],
        client_name="llmwiki-pipeline-teams",
        system_prompt=TEAMS_SYSTEM_PROMPT,
    ),
}

SOURCE_KEYS = list(SOURCES.keys())


def source_or_raise(source_key: str) -> Source:
    src = SOURCES.get(source_key)
    if src is None:
        raise ValueError(f"Unknown MCP source: {source_key}")
    return src


def parse_source_keys(value) -> list[str]:
    """Validate + normalise a list/CSV of requested source keys."""
    if isinstance(value, (list, tuple)):
        raw = list(value)
    elif isinstance(value, str):
        raw = value.split(",")
    else:
        raw = []
    keys = [str(s).strip() for s in raw if str(s).strip()]
    valid = [k for k in keys if k in SOURCE_KEYS]
    # de-dupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for k in valid:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


@dataclass
class LLMConfig:
    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_deployment: str = ""
    azure_api_version: str = "2024-10-21"
    # Entra ID (Azure AD) token scope for data-plane inference.
    azure_token_scope: str = "https://cognitiveservices.azure.com/.default"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


@dataclass
class Config:
    tenant_id: str = TENANT_ID
    client_id: str = ""
    client_secret: str = ""
    authority: str = ""
    auth_mode: str = "device_code"
    token_cache_path: str = ".token_cache.json"
    wiki_dir: str = "app/wiki"
    llm: LLMConfig = field(default_factory=LLMConfig)


config = Config(
    tenant_id=TENANT_ID,
    client_id=os.environ.get("CLIENT_ID", ""),
    client_secret=os.environ.get("CLIENT_SECRET", ""),
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    auth_mode=os.environ.get("AUTH_MODE", "device_code").strip() or "device_code",
    token_cache_path=os.environ.get("TOKEN_CACHE_PATH", ".token_cache.json"),
    wiki_dir=os.environ.get("WIKI_DIR", "app/wiki"),
    llm=LLMConfig(
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
        azure_api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
        azure_api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    ),
)


def llm_provider() -> str | None:
    """Return the active LLM provider name, or None if none is configured.

    Azure is used when endpoint + deployment are set (auth by API key if given,
    otherwise Entra ID). Otherwise OpenAI when an API key is present.
    """
    if config.llm.azure_endpoint and config.llm.azure_deployment:
        return "azure"
    if config.llm.openai_api_key:
        return "openai"
    return None


def assert_client_id() -> None:
    if not config.client_id:
        raise RuntimeError(
            "CLIENT_ID is not set. Copy .env.example to .env and set your Entra "
            "app registration's Application (client) ID."
        )


def wiki_path() -> Path:
    """Absolute path to the wiki output directory."""
    p = Path(config.wiki_dir)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def token_cache_file() -> Path:
    p = Path(config.token_cache_path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p
