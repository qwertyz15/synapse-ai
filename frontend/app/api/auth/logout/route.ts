import { NextRequest, NextResponse } from "next/server";

import { clearAccount } from "@/lib/server/account";
import { clearSession } from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

// The GitHub connection is per browser, so it goes too; the next person to sign in here starts clean.
export function POST(req: NextRequest) {
  const res = NextResponse.json({ ok: true });
  clearAccount(res, req);
  clearSession(res, req);
  return res;
}
