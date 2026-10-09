import { NextRequest, NextResponse } from "next/server";

import { authEnabled, readAccount } from "@/lib/server/account";

export const dynamic = "force-dynamic";

export function GET(req: NextRequest) {
  const account = authEnabled() ? readAccount(req) : null;
  return NextResponse.json(
    {
      enabled: authEnabled(),
      account: account && {
        email: account.email,
        name: account.name,
        avatar_url: account.avatarUrl,
        is_admin: account.isAdmin,
      },
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
