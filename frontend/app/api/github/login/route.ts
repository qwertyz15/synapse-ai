import { NextRequest, NextResponse } from "next/server";

import { authorizeUrl, githubConfig, randomToken, safeReturnTo, writeOAuthState } from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

export function GET(req: NextRequest) {
  const config = githubConfig();
  if (!config) return NextResponse.redirect(new URL("/?github=error&reason=not_configured", req.url));
  const returnTo = safeReturnTo(req.nextUrl.searchParams.get("returnTo"));
  const oauth = { state: randomToken(), verifier: randomToken(), returnTo };
  const res = NextResponse.redirect(authorizeUrl(config.clientId, req, oauth));
  writeOAuthState(res, req, oauth, config.key);
  return res;
}
