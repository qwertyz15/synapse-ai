import { NextRequest, NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  clearSession,
  githubConfig,
  revokeGrant,
  unseal,
  type GithubSession,
} from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const config = githubConfig();
  const session = config ? unseal<GithubSession>(req.cookies.get(SESSION_COOKIE)?.value, config.key) : null;
  if (config && session) await revokeGrant(config, session.accessToken);
  const res = NextResponse.json({ connected: false });
  clearSession(res, req);
  return res;
}
