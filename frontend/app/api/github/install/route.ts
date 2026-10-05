import { NextRequest, NextResponse } from "next/server";

import {
  MANAGE_INSTALLATIONS_URL,
  githubConfig,
  installUrl,
  randomToken,
  writeOAuthState,
} from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

export function GET(req: NextRequest) {
  const config = githubConfig();
  if (!config?.appSlug) return NextResponse.redirect(MANAGE_INSTALLATIONS_URL);
  const requested = req.nextUrl.searchParams.get("returnTo") ?? "/";
  const returnTo = requested.startsWith("/") && !requested.startsWith("//") ? requested : "/";
  const oauth = { state: randomToken(), returnTo };
  const res = NextResponse.redirect(installUrl(config.appSlug, oauth.state));
  writeOAuthState(res, req, oauth, config.key);
  return res;
}
