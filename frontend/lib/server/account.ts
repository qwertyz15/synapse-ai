import "server-only";

import type { NextRequest, NextResponse } from "next/server";

import { cookieOptions, pkceChallenge, seal, sessionKey, unseal } from "./session-crypto";

export const ACCOUNT_COOKIE = "account";
export const SIGN_IN_COOKIE = "account_oauth";

const GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN = "https://oauth2.googleapis.com/token";
const GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo";
const SESSION_MAX_AGE_S = 60 * 60 * 24 * 30;

export type AccountSession = {
  id: string;
  email: string;
  name: string | null;
  avatarUrl: string | null;
  isAdmin: boolean;
  expiresAt: number;
};

export type SignInState = { state: string; verifier: string; returnTo: string };

export type GoogleProfile = {
  sub: string;
  email: string;
  email_verified: boolean;
  name?: string;
  picture?: string;
};

export const authEnabled = () => process.env.AUTH_ENABLED === "true";

export function googleConfig() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const key = sessionKey();
  if (!clientId || !clientSecret || !key) return null;
  return { clientId, clientSecret, key };
}

type GoogleConfig = NonNullable<ReturnType<typeof googleConfig>>;

/** The signed-in account, or null when there is none, it expired, or sign-in isn't configured. */
export function readAccount(req: Pick<NextRequest, "cookies">, now = Date.now()): AccountSession | null {
  const key = sessionKey();
  if (!key) return null;
  const session = unseal<AccountSession>(req.cookies.get(ACCOUNT_COOKIE)?.value, key);
  return session && session.expiresAt > now ? session : null;
}

export function writeAccount(res: NextResponse, req: NextRequest, account: Omit<AccountSession, "expiresAt">) {
  const key = sessionKey();
  if (!key) return;
  const session: AccountSession = { ...account, expiresAt: Date.now() + SESSION_MAX_AGE_S * 1000 };
  res.cookies.set(ACCOUNT_COOKIE, seal(session, key), cookieOptions(req, SESSION_MAX_AGE_S));
}

export function clearAccount(res: NextResponse, req: NextRequest) {
  res.cookies.set(ACCOUNT_COOKIE, "", cookieOptions(req, 0));
}

export function writeSignInState(res: NextResponse, req: NextRequest, state: SignInState, key: Buffer) {
  res.cookies.set(SIGN_IN_COOKIE, seal(state, key), { ...cookieOptions(req, 600), path: "/api/auth" });
}

export function clearSignInState(res: NextResponse, req: NextRequest) {
  res.cookies.set(SIGN_IN_COOKIE, "", { ...cookieOptions(req, 0), path: "/api/auth" });
}

export function googleRedirectUri(req: NextRequest): string {
  return process.env.GOOGLE_REDIRECT_URI || new URL("/api/auth/callback", req.nextUrl.origin).toString();
}

export function googleAuthorizeUrl(config: GoogleConfig, req: NextRequest, state: SignInState): string {
  const url = new URL(GOOGLE_AUTHORIZE);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", googleRedirectUri(req));
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", "openid email profile");
  url.searchParams.set("state", state.state);
  url.searchParams.set("code_challenge", pkceChallenge(state.verifier));
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("prompt", "select_account");
  return url.toString();
}

export async function fetchGoogleProfile(
  config: GoogleConfig,
  req: NextRequest,
  code: string,
  verifier: string,
): Promise<GoogleProfile> {
  const tokenRes = await fetch(GOOGLE_TOKEN, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      code,
      client_id: config.clientId,
      client_secret: config.clientSecret,
      redirect_uri: googleRedirectUri(req),
      grant_type: "authorization_code",
      code_verifier: verifier,
    }),
    cache: "no-store",
  });
  const tokens = await tokenRes.json().catch(() => ({}));
  if (!tokenRes.ok || !tokens.access_token) throw new Error(tokens.error ?? `token_http_${tokenRes.status}`);

  const profileRes = await fetch(GOOGLE_USERINFO, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
    cache: "no-store",
  });
  if (!profileRes.ok) throw new Error(`userinfo_http_${profileRes.status}`);
  return profileRes.json();
}

export type SignInResult =
  | { ok: true; account: Omit<AccountSession, "expiresAt"> }
  | { ok: false; reason: "not_allowed" | "blocked" | "failed" };

/** Creates or updates the account in the agent service, which also applies the sign-up rules. */
export async function signInToService(profile: GoogleProfile, anonymousUserId?: string): Promise<SignInResult> {
  const agentUrl = (process.env.AGENT_URL ?? "http://localhost:8080").replace(/\/$/, "");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (process.env.AUTH_SECRET) headers.Authorization = `Bearer ${process.env.AUTH_SECRET}`;
  const res = await fetch(`${agentUrl}/auth/sign-in`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      google_sub: profile.sub,
      email: profile.email,
      email_verified: profile.email_verified === true,
      name: profile.name ?? null,
      avatar_url: profile.picture ?? null,
      anonymous_user_id: anonymousUserId ?? null,
    }),
    cache: "no-store",
  });
  if (res.status === 403) {
    const body = await res.json().catch(() => ({}));
    return { ok: false, reason: body.code === "blocked" ? "blocked" : "not_allowed" };
  }
  if (!res.ok) return { ok: false, reason: "failed" };
  const account = await res.json();
  return {
    ok: true,
    account: {
      id: account.id,
      email: account.email,
      name: account.name ?? null,
      avatarUrl: account.avatar_url ?? null,
      isAdmin: account.is_admin === true,
    },
  };
}
