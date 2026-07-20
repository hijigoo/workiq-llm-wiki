"""Microsoft Entra ID authentication for the MCP sources.

The web app signs the user in interactively with the **Authorization Code
flow** (browser redirect), exactly like ``samples/mcp-web-sample``:

* The app authenticates itself as a **confidential client** using
  ``CLIENT_SECRET`` when one is set (falls back to a public client + PKCE when
  it isn't). MSAL's ``initiate_auth_code_flow`` / ``acquire_token_by_auth_code_flow``
  handle PKCE and state internally.
* Login is **per source** because Mail and Teams are different OAuth resources
  (each ``<mcp-url>/.default``). A first sign-in establishes the account; the
  session then acquires a token per source silently, and a source that hasn't
  been consented yet just shows a "connect" prompt (incremental consent).
* The signed-in account is identified by its ``home_account_id`` (stored in the
  per-user server session); tokens live in the MSAL token cache, never in the
  session cookie.

The older ``device_code`` / ``client_credentials`` helpers below are kept for
notebook / non-interactive use. ``get_access_token`` returns ``None`` (never
raises for auth reasons) when a token cannot be obtained silently.
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


def _get_app():
    """MSAL app for the interactive web login: a confidential client when a
    ``CLIENT_SECRET`` is configured (recommended), otherwise a public client
    (PKCE only). Both share the same on-disk token cache."""
    if config.client_secret:
        return _get_confidential_app()
    return _get_public_app()


def build_auth_flow(source_key: str) -> dict:
    """Start an Authorization Code flow for one source and return the MSAL flow
    dict (contains ``auth_uri`` to redirect to, plus PKCE + state to stash in
    the session for the callback)."""
    source = source_or_raise(source_key)
    app = _get_app()
    flow = app.initiate_auth_code_flow(source.scopes, redirect_uri=config.redirect_uri)
    if "auth_uri" not in flow:
        raise RuntimeError(
            f"Failed to start auth-code flow for '{source_key}': "
            f"{flow.get('error_description', flow)}"
        )
    return flow


def redeem_auth_flow(flow: dict, auth_response: dict) -> dict:
    """Exchange the redirect's query params for tokens. ``auth_response`` is the
    dict of callback query parameters (``code``, ``state``, ...). MSAL validates
    state and completes PKCE internally."""
    app = _get_app()
    result = app.acquire_token_by_auth_code_flow(flow, auth_response)
    _persist_cache()
    return result


def resolve_account(result: dict) -> Optional[dict]:
    """Find the MSAL account that a successful auth-code result belongs to."""
    claims = (result or {}).get("id_token_claims", {}) or {}
    oid = claims.get("oid")
    tid = claims.get("tid")
    home = f"{oid}.{tid}" if oid and tid else None
    app = _get_app()
    accounts = app.get_accounts()
    for acc in accounts:
        if home and acc.get("home_account_id") == home:
            return acc
        if oid and acc.get("local_account_id") == oid:
            return acc
    return accounts[0] if accounts else None


def token_for_account(home_account_id: Optional[str], source_key: str) -> Optional[str]:
    """Silently acquire an access token for ``source_key`` for the given signed-in
    account. Returns ``None`` when the account is unknown or the source hasn't
    been consented yet (interaction required)."""
    source = source_or_raise(source_key)
    if not home_account_id:
        return None
    app = _get_app()
    account = next(
        (a for a in app.get_accounts() if a.get("home_account_id") == home_account_id),
        None,
    )
    if account is None:
        return None
    result = app.acquire_token_silent(source.scopes, account=account)
    _persist_cache()
    if result and "access_token" in result:
        return result["access_token"]
    return None


def remove_account(home_account_id: Optional[str]) -> None:
    """Drop one account (and its cached tokens) — used on web logout."""
    if not home_account_id:
        return
    app = _get_app()
    for acc in app.get_accounts():
        if acc.get("home_account_id") == home_account_id:
            try:
                app.remove_account(acc)
            except Exception:  # noqa: BLE001
                pass
    _persist_cache()


def logout() -> list[str]:
    """Sign out of every source: drop cached accounts, delete the token cache
    file and reset the in-memory MSAL state so status flips immediately (no
    server restart needed). Returns the usernames that were removed."""
    global _cache, _public_app, _confidential_app
    removed: list[str] = []
    try:
        app = _get_public_app()
        for acc in app.get_accounts():
            removed.append(acc.get("username", "?"))
            app.remove_account(acc)
    except Exception:  # noqa: BLE001 - logout must not raise on partial state
        pass
    path = token_cache_file()
    if path.exists():
        try:
            path.unlink()
        except Exception:  # noqa: BLE001
            pass
    _cache = None
    _public_app = None
    _confidential_app = None
    return removed


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
