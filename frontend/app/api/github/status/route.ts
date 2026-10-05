import { NextRequest, NextResponse } from "next/server";

import {
  MANAGE_INSTALLATIONS_URL,
  clearSession,
  countInstallations,
  githubConfig,
  resolveSession,
  writeSession,
} from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const { session, updated, cleared } = await resolveSession(req);
  const installations = session ? await countInstallations(session.accessToken) : null;
  const res = NextResponse.json({
    configured: githubConfig() !== null,
    connected: session !== null,
    login: session?.login ?? null,
    avatar_url: session?.avatarUrl ?? null,
    installed: installations === null ? null : installations > 0,
    manage_url: MANAGE_INSTALLATIONS_URL,
  });
  if (session && updated) writeSession(res, req, session);
  if (cleared) clearSession(res, req);
  return res;
}
