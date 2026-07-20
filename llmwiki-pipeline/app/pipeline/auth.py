"""Microsoft Entra ID authentication for the MCP sources.

Two modes (set via ``AUTH_MODE`` in ``.env``):

* ``device_code`` (default) — delegated user login. The first call prints a
  short code + URL; after the user signs in once, the token is cached to
  ``TOKEN_CACHE_PATH`` and every later call is silent. The Work IQ Mail/Teams
  MCP servers expose *delegated* scopes (``McpServers.Mail.All`` /
  ``McpServers.Teams.All``), so this is the reliable default.
* ``client_credentials`` — app-only token via ``CLIENT_SECRET`` (only works if
  your tenant grants the app *application* permissions to the MCP resource).

A token is acquired **per source** because Mail and Teams are different OAuth
resources. ``get_access_token`` returns ``None`` (never raises for auth
reasons) when a token cannot be obtained silently, so callers can decide to
trigger an interactive login.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

import msal

from .config import assert_client_id, config, source_or_raise, token_cache_file

_confidential_app: Optional[msal.ConfidentialClientApplication] = None
_public_app: Optional[msal.PublicClientApplication] = None
_cache: Optional[msal.SerializableTokenCache] = None


def _load_cache() -> msal.SerializableTokenCache:
    global _cache
    if _cache is not None:
        return _cache
    cache = msal.SerializableTokenCache()
    path = token_cache_file()
    if path.exists():
        try:
            cache.deserialize(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - corrupt cache should not be fatal
            pass
    _cache = cache
    return cache


def _persist_cache() -> None:
    if _cache is not None and _cache.has_state_changed:
        token_cache_file().write_text(_cache.serialize(), encoding="utf-8")


def _get_public_app() -> msal.PublicClientApplication:
    global _public_app
    if _public_app is None:
        assert_client_id()
        _public_app = msal.PublicClientApplication(
            config.client_id,
            authority=config.authority,
            token_cache=_load_cache(),
        )
    return _public_app


def _get_confidential_app() -> msal.ConfidentialClientApplication:
    global _confidential_app
    if _confidential_app is None:
        assert_client_id()
        if not config.client_secret:
            raise RuntimeError(
                "AUTH_MODE=client_credentials requires CLIENT_SECRET in .env."
            )
        _confidential_app = msal.ConfidentialClientApplication(
            config.client_id,
            authority=config.authority,
            client_credential=config.client_secret,
            token_cache=_load_cache(),
        )
    return _confidential_app


def _acquire_client_credentials(source_key: str) -> Optional[str]:
    source = source_or_raise(source_key)
    app = _get_confidential_app()
    result = app.acquire_token_for_client(scopes=source.scopes)
    _persist_cache()
    if result and "access_token" in result:
        return result["access_token"]
    print(
        f"[auth] client-credentials token failed for '{source_key}': "
        f"{result.get('error_description', result)}",
        file=sys.stderr,
    )
    return None


def _acquire_silent(source_key: str) -> Optional[str]:
    source = source_or_raise(source_key)
    app = _get_public_app()
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(source.scopes, account=accounts[0])
    _persist_cache()
    if result and "access_token" in result:
        return result["access_token"]
    return None


def login_device_code(
    source_key: str, prompt: Callable[[str], None] | None = None
) -> str:
    """Interactively acquire a delegated token via device-code flow.

    ``prompt`` receives the human-readable instruction message (defaults to
    printing it). Returns the access token, or raises on failure.
    """
    source = source_or_raise(source_key)
    app = _get_public_app()

    # Reuse a cached token if one is already available.
    token = _acquire_silent(source_key)
    if token:
        return token

    flow = app.initiate_device_flow(scopes=source.scopes)
    if "user_code" not in flow:
        raise RuntimeError(
            f"Failed to start device flow for '{source_key}': "
            f"{flow.get('error_description', flow)}"
        )
    message = flow["message"]
    (prompt or print)(message)

    result = app.acquire_token_by_device_flow(flow)
    _persist_cache()
    if result and "access_token" in result:
        return result["access_token"]
    raise RuntimeError(
        f"Device-code login failed for '{source_key}': "
        f"{result.get('error_description', result)}"
    )


def get_access_token(source_key: str) -> Optional[str]:
    """Silently acquire an access token for one source.

    Returns ``None`` (never raises for auth reasons) when no token can be
    obtained without interaction — the caller can then call
    ``login_device_code`` for that specific source.
    """
    source_or_raise(source_key)
    if config.auth_mode == "client_credentials":
        return _acquire_client_credentials(source_key)
    return _acquire_silent(source_key)


def ensure_access_token(
    source_key: str, prompt: Callable[[str], None] | None = None
) -> str:
    """Return a valid token, triggering an interactive login if needed.

    In ``client_credentials`` mode this never prompts. In ``device_code`` mode
    it first tries silently, then falls back to the device-code flow.
    """
    if config.auth_mode == "client_credentials":
        token = _acquire_client_credentials(source_key)
        if not token:
            raise RuntimeError(
                f"Could not acquire app-only token for '{source_key}'."
            )
        return token
    return login_device_code(source_key, prompt=prompt)


def tokens_for_sources(source_keys: list[str]) -> dict[str, str]:
    """Silently gather tokens for the given sources; skips ones without a
    token (not yet signed in). Use ``ensure_access_token`` per source to
    trigger login."""
    out: dict[str, str] = {}
    for key in source_keys:
        token = get_access_token(key)
        if token:
            out[key] = token
    return out
