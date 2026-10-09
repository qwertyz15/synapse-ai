import { NextResponse, type NextRequest } from "next/server";

import { USER_COOKIE } from "@/lib/constants";
import { authEnabled, readAccount } from "@/lib/server/account";

// Issue the anonymous browser id on page loads so the parallel API calls a page makes all share it.
// With sign-in on, pages need an account; the anonymous id is still issued so that chats from
// before sign-in was turned on can move to the account at first sign-in.
export function proxy(request: NextRequest) {
  let res = NextResponse.next();
  if (authEnabled()) {
    const signedIn = readAccount(request) !== null;
    const onLogin = request.nextUrl.pathname === "/login";
    if (!signedIn && !onLogin) {
      const login = new URL("/login", request.url);
      login.searchParams.set("returnTo", `${request.nextUrl.pathname}${request.nextUrl.search}`);
      res = NextResponse.redirect(login);
    } else if (signedIn && onLogin) {
      res = NextResponse.redirect(new URL("/", request.url));
    }
  }
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
