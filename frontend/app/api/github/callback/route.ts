import { timingSafeEqual } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

import {
  OAUTH_COOKIE,
  SESSION_COOKIE,
  clearOAuthState,
  countInstallations,
  exchangeCode,
  githubConfig,
  installUrl,
  randomToken,
  unseal,
  writeOAuthState,
  writeSession,
  type GithubSession,
  type OAuthState,
} from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

const sameString = (a: string, b: string) => a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));

function backTo(req: NextRequest, returnTo: string, result: "connected" | "error", reason?: string) {
  const url = new URL(returnTo, req.url);
  url.searchParams.set("github", result);
  if (reason) url.searchParams.set("reason", reason);
  const res = NextResponse.redirect(url);
  clearOAuthState(res, req);
  return res;
}

// Handles both GitHub legs: user authorization (login/oauth) and app installation, which
// GitHub sends here too because the app requests user authorization during installation.
export async function GET(req: NextRequest) {
  const config = githubConfig();
  if (!config) return backTo(req, "/", "error", "not_configured");

  const params = req.nextUrl.searchParams;
  const fromInstall = params.has("installation_id") || params.has("setup_action");
  const existing = unseal<GithubSession>(req.cookies.get(SESSION_COOKIE)?.value, config.key);
  const oauth = unseal<OAuthState>(req.cookies.get(OAUTH_COOKIE)?.value, config.key);
  const state = params.get("state");

  if (!oauth || !state || !sameString(state, oauth.state)) {
    // Installed or reconfigured from GitHub's own pages: the token we already hold sees the new repos.
    if (fromInstall && existing) return backTo(req, "/", "connected");
    return backTo(req, "/", "error", "invalid_state");
  }
  if (params.get("error")) return backTo(req, oauth.returnTo, "error", params.get("error") ?? "denied");

  const code = params.get("code");
  if (!code) {
    return fromInstall && existing
      ? backTo(req, oauth.returnTo, "connected")
      : backTo(req, oauth.returnTo, "error", "missing_code");
  }

  let session: GithubSession;
  try {
    session = await exchangeCode(config, req, code, oauth.verifier);
  } catch (err) {
    console.error("GitHub connect failed:", err instanceof Error ? err.message : err);
    return backTo(req, oauth.returnTo, "error", "exchange_failed");
  }

  if (!fromInstall && config.appSlug && (await countInstallations(session.accessToken)) === 0) {
    const next: OAuthState = { state: randomToken(), returnTo: oauth.returnTo };
    const res = NextResponse.redirect(installUrl(config.appSlug, next.state));
    writeOAuthState(res, req, next, config.key);
    writeSession(res, req, session);
    return res;
  }

  const res = backTo(req, oauth.returnTo, "connected");
  writeSession(res, req, session);
  return res;
}
