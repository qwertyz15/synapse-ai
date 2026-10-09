import { NextRequest, NextResponse } from "next/server";

import { authEnabled, googleAuthorizeUrl, googleConfig, writeSignInState } from "@/lib/server/account";
import { randomToken, safeReturnTo } from "@/lib/server/session-crypto";

export const dynamic = "force-dynamic";

export function GET(req: NextRequest) {
  if (!authEnabled()) return NextResponse.redirect(new URL("/", req.url));
  const config = googleConfig();
  if (!config) return NextResponse.redirect(new URL("/login?error=not_configured", req.url));
  const state = {
    state: randomToken(),
    verifier: randomToken(),
    returnTo: safeReturnTo(req.nextUrl.searchParams.get("returnTo")),
  };
  const res = NextResponse.redirect(googleAuthorizeUrl(config, req, state));
  writeSignInState(res, req, state, config.key);
  return res;
}
