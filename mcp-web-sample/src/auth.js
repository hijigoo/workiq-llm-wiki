import {
  PublicClientApplication,
  ConfidentialClientApplication,
  CryptoProvider,
  LogLevel,
} from "@azure/msal-node";
import { config, assertClientId, SOURCES } from "./config.js";

let msalApp = null;
const cryptoProvider = new CryptoProvider();

function getApp() {
  if (msalApp) return msalApp;
  assertClientId();

  const auth = {
    clientId: config.clientId,
    authority: config.authority,
  };
  if (config.clientSecret) auth.clientSecret = config.clientSecret;

  const options = {
    auth,
    system: {
      loggerOptions: {
        loggerCallback(level, message) {
          if (level === LogLevel.Error) console.error("[msal]", message);
        },
        piiLoggingEnabled: false,
        logLevel: LogLevel.Warning,
      },
    },
  };

  msalApp = config.clientSecret
    ? new ConfidentialClientApplication(options)
    : new PublicClientApplication(options);
  return msalApp;
}

function sourceOrThrow(sourceKey) {
  const source = SOURCES[sourceKey];
  if (!source) throw new Error(`Unknown MCP source: ${sourceKey}`);
  return source;
}

/**
 * Build the Entra authorization URL for ONE source and stash the PKCE
 * verifier + state + target source in session. Each source is a distinct
 * OAuth resource, so login is always scoped to a single source at a time —
 * this also enables incremental consent (connect Mail now, Teams later).
 */
export async function getAuthCodeUrl(session, sourceKey) {
  const source = sourceOrThrow(sourceKey);
  const app = getApp();
  const { verifier, challenge } = await cryptoProvider.generatePkceCodes();
  const state = cryptoProvider.createNewGuid();
  session.pkceVerifier = verifier;
  session.authState = state;
  session.authSource = sourceKey;

  return app.getAuthCodeUrl({
    scopes: source.scopes,
    redirectUri: config.redirectUri,
    codeChallenge: challenge,
    codeChallengeMethod: "S256",
    state,
  });
}

/** Exchange the authorization code for tokens; persist the account + connected source in session. */
export async function handleAuthCallback(session, code, state) {
  const app = getApp();
  if (!session.authState || session.authState !== state) {
    throw new Error("State mismatch — possible CSRF or expired login. Try signing in again.");
  }
  const sourceKey = session.authSource;
  const source = sourceOrThrow(sourceKey);

  const result = await app.acquireTokenByCode({
    code,
    scopes: source.scopes,
    redirectUri: config.redirectUri,
    codeVerifier: session.pkceVerifier,
    state,
  });
  session.homeAccountId = result.account?.homeAccountId || null;
  session.username = result.account?.username || null;
  session.name = result.account?.name || null;
  session.connectedSources = session.connectedSources || {};
  session.connectedSources[sourceKey] = true;
  delete session.pkceVerifier;
  delete session.authState;
  delete session.authSource;
  return { result, sourceKey };
}

/**
 * Silently acquire a fresh access token for the signed-in account, scoped to
 * ONE source. Returns null (never throws for auth reasons) when no token can
 * be obtained silently — e.g. the user hasn't connected that source yet, so
 * the caller can prompt for that specific source's login.
 */
export async function getAccessToken(session, sourceKey) {
  const source = sourceOrThrow(sourceKey);
  if (!session.homeAccountId) return null;
  const app = getApp();
  const cache = app.getTokenCache();
  const account = await cache.getAccountByHomeId(session.homeAccountId);
  if (!account) return null;

  try {
    const result = await app.acquireTokenSilent({
      account,
      scopes: source.scopes,
    });
    session.connectedSources = session.connectedSources || {};
    session.connectedSources[sourceKey] = true;
    return result.accessToken;
  } catch (err) {
    // Interaction/consent required for this specific resource — not a hard
    // error, just means this source needs its own /auth/login?source=...
    console.error(`[auth] silent token acquisition failed for "${sourceKey}":`, err.message);
    return null;
  }
}

export async function signOut(session) {
  if (session.homeAccountId) {
    const app = getApp();
    const cache = app.getTokenCache();
    const account = await cache.getAccountByHomeId(session.homeAccountId);
    if (account) await cache.removeAccount(account);
  }
}
