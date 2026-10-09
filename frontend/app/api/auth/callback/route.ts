import { timingSafeEqual } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

import { USER_COOKIE } from "@/lib/constants";
import {
  SIGN_IN_COOKIE,
  clearSignInState,
  fetchGoogleProfile,
  googleConfig,
  signInToService,
  writeAccount,
  type SignInState,
} from "@/lib/server/account";
import { safeReturnTo, unseal } from "@/lib/server/session-crypto";

export const dynamic = "force-dynamic";

const sameString = (a: string, b: string) => a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));

function toLogin(req: NextRequest, error: string) {
  const res = NextResponse.redirect(new URL(`/login?error=${error}`, req.url));
  clearSignInState(res, req);
  return res;
}

export async function GET(req: NextRequest) {
  const config = googleConfig();
  if (!config) return toLogin(req, "not_configured");

  const params = req.nextUrl.searchParams;
  const saved = unseal<SignInState>(req.cookies.get(SIGN_IN_COOKIE)?.value, config.key);
  const state = params.get("state");
  if (!saved || !state || !sameString(state, saved.state)) return toLogin(req, "expired");
  if (params.get("error")) return toLogin(req, "denied");
  const code = params.get("code");
  if (!code) return toLogin(req, "failed");

  try {
    const profile = await fetchGoogleProfile(config, req, code, saved.verifier);
    if (profile.email_verified !== true) return toLogin(req, "unverified");
    const result = await signInToService(profile, req.cookies.get(USER_COOKIE)?.value);
    if (!result.ok) return toLogin(req, result.reason);
    const res = NextResponse.redirect(new URL(safeReturnTo(saved.returnTo), req.url));
    clearSignInState(res, req);
    writeAccount(res, req, result.account);
    return res;
  } catch (err) {
    console.error("Google sign-in failed:", err instanceof Error ? err.message : err);
    return toLogin(req, "failed");
  }
}
