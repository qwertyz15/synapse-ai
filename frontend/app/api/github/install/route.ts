import { NextRequest, NextResponse } from "next/server";

import {
  MANAGE_INSTALLATIONS_URL,
  githubConfig,
  installUrl,
  randomToken,
  safeReturnTo,
  writeOAuthState,
} from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

export function GET(req: NextRequest) {
  const config = githubConfig();
  if (!config?.appSlug) return NextResponse.redirect(MANAGE_INSTALLATIONS_URL);
  const returnTo = safeReturnTo(req.nextUrl.searchParams.get("returnTo"));
  const oauth = { state: randomToken(), returnTo };
  const res = NextResponse.redirect(installUrl(config.appSlug, oauth.state));
  writeOAuthState(res, req, oauth, config.key);
  return res;
}
