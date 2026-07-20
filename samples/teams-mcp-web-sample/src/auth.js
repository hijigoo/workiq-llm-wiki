import {
  PublicClientApplication,
  ConfidentialClientApplication,
  CryptoProvider,
  LogLevel,
} from "@azure/msal-node";
import { config, assertClientId } from "./config.js";

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

/** Build the Entra authorization URL and stash the PKCE verifier + state in session. */
export async function getAuthCodeUrl(session) {
  const app = getApp();
  const { verifier, challenge } = await cryptoProvider.generatePkceCodes();
  const state = cryptoProvider.createNewGuid();
  session.pkceVerifier = verifier;
  session.authState = state;

  return app.getAuthCodeUrl({
    scopes: config.scopes,
    redirectUri: config.redirectUri,
    codeChallenge: challenge,
    codeChallengeMethod: "S256",
    state,
  });
}

/** Exchange the authorization code for tokens; persist the account id in session. */
export async function handleAuthCallback(session, code, state) {
  const app = getApp();
  if (!session.authState || session.authState !== state) {
    throw new Error("State mismatch — possible CSRF or expired login. Try signing in again.");
  }
  const result = await app.acquireTokenByCode({
    code,
    scopes: config.scopes,
    redirectUri: config.redirectUri,
    codeVerifier: session.pkceVerifier,
    state,
  });
  session.homeAccountId = result.account?.homeAccountId || null;
  session.username = result.account?.username || null;
  session.name = result.account?.name || null;
  delete session.pkceVerifier;
  delete session.authState;
  return result;
}

/** Silently acquire a fresh access token for the signed-in account. */
export async function getAccessToken(session) {
  if (!session.homeAccountId) return null;
  const app = getApp();
  const cache = app.getTokenCache();
  const account = await cache.getAccountByHomeId(session.homeAccountId);
  if (!account) return null;

  try {
    const result = await app.acquireTokenSilent({
      account,
      scopes: config.scopes,
    });
    return result.accessToken;
  } catch (err) {
    console.error("[auth] silent token acquisition failed:", err.message);
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
