import { NextResponse, type NextRequest } from "next/server";

import { USER_COOKIE } from "@/lib/constants";

// Issue the anonymous browser id on page loads so the parallel API calls a page makes all share it.
export function proxy(request: NextRequest) {
  const res = NextResponse.next();
  if (!request.cookies.has(USER_COOKIE)) {
    res.cookies.set(USER_COOKIE, crypto.randomUUID(), {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 400,
    });
  }
  return res;
}

export const config = {
  // /api is excluded so large uploads aren't buffered by the proxy layer.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|ico)$).*)"],
};
