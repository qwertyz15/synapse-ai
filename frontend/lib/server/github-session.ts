import "server-only";

import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

import type { NextRequest, NextResponse } from "next/server";

export const SESSION_COOKIE = "gh_session";
export const OAUTH_COOKIE = "gh_oauth";

const GITHUB = "https://github.com";
const REFRESH_MARGIN_MS = 60_000;
const SESSION_MAX_AGE_S = 60 * 60 * 24 * 180;

export type GithubSession = {
  accessToken: string;
  refreshToken?: string;
  expiresAt?: number;
  refreshExpiresAt?: number;
  login: string;
  avatarUrl: string;
};

// `verifier` is absent for the app-installation leg, where GitHub doesn't support PKCE.
export type OAuthState = { state: string; verifier?: string; returnTo: string };

type TokenResponse = {
  access_token?: string;
  expires_in?: number;
  refresh_token?: string;
  refresh_token_expires_in?: number;
  error?: string;
  error_description?: string;
};

export function githubConfig() {
  const clientId = process.env.GITHUB_CLIENT_ID;
  const clientSecret = process.env.GITHUB_CLIENT_SECRET;
  const secret = process.env.WEB_SESSION_SECRET;
  if (!clientId || !clientSecret || !secret) return null;
  const appSlug = process.env.GITHUB_APP_SLUG || null;
  return { clientId, clientSecret, appSlug, key: createHash("sha256").update(secret).digest() };
}

export const installUrl = (appSlug: string, state?: string) => {
  const url = new URL(`${GITHUB}/apps/${encodeURIComponent(appSlug)}/installations/new`);
  if (state) url.searchParams.set("state", state);
  return url.toString();
};

export const MANAGE_INSTALLATIONS_URL = `${GITHUB}/settings/installations`;

/** Number of installations of this app the user can access, or null if GitHub couldn't be asked. */
export async function countInstallations(accessToken: string): Promise<number | null> {
  try {
    const res = await fetch("https://api.github.com/user/installations?per_page=1", {
      headers: { Authorization: `Bearer ${accessToken}`, Accept: "application/vnd.github+json" },
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = await res.json();
    return typeof body.total_count === "number" ? body.total_count : null;
  } catch {
    return null;
  }
}

export function seal(value: unknown, key: Buffer): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const body = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64url");
}

export function unseal<T>(sealed: string | undefined, key: Buffer): T | null {
  if (!sealed) return null;
  try {
    const raw = Buffer.from(sealed, "base64url");
    const decipher = createDecipheriv("aes-256-gcm", key, raw.subarray(0, 12));
    decipher.setAuthTag(raw.subarray(12, 28));
    const text = Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString("utf8");
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export const randomToken = () => randomBytes(32).toString("base64url");

export const pkceChallenge = (verifier: string) => createHash("sha256").update(verifier).digest("base64url");

export function redirectUri(req: NextRequest): string {
  return process.env.GITHUB_REDIRECT_URI ?? new URL("/api/github/callback", req.nextUrl.origin).toString();
}

export function authorizeUrl(clientId: string, req: NextRequest, oauth: OAuthState & { verifier: string }): string {
  const url = new URL(`${GITHUB}/login/oauth/authorize`);
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", redirectUri(req));
  url.searchParams.set("state", oauth.state);
  url.searchParams.set("code_challenge", pkceChallenge(oauth.verifier));
  url.searchParams.set("code_challenge_method", "S256");
  return url.toString();
}

async function tokenRequest(params: Record<string, string>): Promise<TokenResponse> {
  const res = await fetch(`${GITHUB}/login/oauth/access_token`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(params),
    cache: "no-store",
  });
  if (!res.ok) return { error: `http_${res.status}` };
  return res.json();
}

function toSession(tokens: TokenResponse, user: Pick<GithubSession, "login" | "avatarUrl">): GithubSession {
  const now = Date.now();
  return {
    accessToken: tokens.access_token!,
    refreshToken: tokens.refresh_token,
    expiresAt: tokens.expires_in ? now + tokens.expires_in * 1000 : undefined,
    refreshExpiresAt: tokens.refresh_token_expires_in ? now + tokens.refresh_token_expires_in * 1000 : undefined,
    ...user,
  };
}

export async function exchangeCode(
  config: NonNullable<ReturnType<typeof githubConfig>>,
  req: NextRequest,
  code: string,
  verifier?: string,
): Promise<GithubSession> {
  const tokens = await tokenRequest({
    client_id: config.clientId,
    client_secret: config.clientSecret,
    code,
    redirect_uri: redirectUri(req),
    ...(verifier ? { code_verifier: verifier } : {}),
  });
  if (!tokens.access_token) throw new Error(tokens.error_description ?? tokens.error ?? "token_exchange_failed");

  const userRes = await fetch("https://api.github.com/user", {
    headers: { Authorization: `Bearer ${tokens.access_token}`, Accept: "application/vnd.github+json" },
    cache: "no-store",
  });
  if (!userRes.ok) throw new Error(`user_lookup_failed_${userRes.status}`);
  const user = await userRes.json();
  return toSession(tokens, { login: user.login, avatarUrl: user.avatar_url });
}

export function needsRefresh(session: GithubSession, now = Date.now()): boolean {
  return session.expiresAt !== undefined && session.expiresAt - REFRESH_MARGIN_MS <= now;
}

export function canRefresh(session: GithubSession, now = Date.now()): boolean {
  return !!session.refreshToken && (session.refreshExpiresAt === undefined || session.refreshExpiresAt > now);
}

async function refresh(
  config: NonNullable<ReturnType<typeof githubConfig>>,
  session: GithubSession,
): Promise<GithubSession | null> {
  const tokens = await tokenRequest({
    client_id: config.clientId,
    client_secret: config.clientSecret,
    grant_type: "refresh_token",
    refresh_token: session.refreshToken!,
  });
  if (!tokens.access_token) return null;
  return toSession(tokens, { login: session.login, avatarUrl: session.avatarUrl });
}

/** Returns the caller's GitHub session, refreshing an expired token; `updated` means the cookie must be rewritten. */
export async function resolveSession(
  req: NextRequest,
): Promise<{ session: GithubSession | null; updated: boolean; cleared: boolean }> {
  const config = githubConfig();
  if (!config) return { session: null, updated: false, cleared: false };
  const raw = req.cookies.get(SESSION_COOKIE)?.value;
  const session = unseal<GithubSession>(raw, config.key);
  if (!session) return { session: null, updated: false, cleared: !!raw };
  if (!needsRefresh(session)) return { session, updated: false, cleared: false };
  const renewed = canRefresh(session) ? await refresh(config, session) : null;
  return renewed
    ? { session: renewed, updated: true, cleared: false }
    : { session: null, updated: false, cleared: true };
}

const cookieOptions = (req: NextRequest, maxAge: number) => ({
  httpOnly: true,
  sameSite: "lax" as const,
  secure: req.nextUrl.protocol === "https:",
  path: "/",
  maxAge,
});

export function writeSession(res: NextResponse, req: NextRequest, session: GithubSession) {
  const config = githubConfig();
  if (!config) return;
  const maxAge = session.refreshExpiresAt
    ? Math.max(60, Math.floor((session.refreshExpiresAt - Date.now()) / 1000))
    : SESSION_MAX_AGE_S;
  res.cookies.set(SESSION_COOKIE, seal(session, config.key), cookieOptions(req, maxAge));
}

export function clearSession(res: NextResponse, req: NextRequest) {
  res.cookies.set(SESSION_COOKIE, "", cookieOptions(req, 0));
}

export function writeOAuthState(res: NextResponse, req: NextRequest, oauth: OAuthState, key: Buffer) {
  res.cookies.set(OAUTH_COOKIE, seal(oauth, key), { ...cookieOptions(req, 600), path: "/api/github" });
}

export function clearOAuthState(res: NextResponse, req: NextRequest) {
  res.cookies.set(OAUTH_COOKIE, "", { ...cookieOptions(req, 0), path: "/api/github" });
}

export async function revokeGrant(config: NonNullable<ReturnType<typeof githubConfig>>, accessToken: string) {
  const basic = Buffer.from(`${config.clientId}:${config.clientSecret}`).toString("base64");
  await fetch(`https://api.github.com/applications/${config.clientId}/grant`, {
    method: "DELETE",
    headers: { Authorization: `Basic ${basic}`, Accept: "application/vnd.github+json" },
    body: JSON.stringify({ access_token: accessToken }),
    cache: "no-store",
  }).catch(() => undefined);
}
