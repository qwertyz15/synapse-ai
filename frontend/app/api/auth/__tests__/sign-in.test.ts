import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET as agentGet, POST as agentPost } from "../../agent/[...path]/route";
import { GET as callback } from "../callback/route";
import { GET as login } from "../login/route";
import { GET as me } from "../me/route";
import { proxy } from "@/proxy";
import { ACCOUNT_COOKIE, SIGN_IN_COOKIE, readAccount } from "@/lib/server/account";
import { seal, sessionKey } from "@/lib/server/session-crypto";

const ORIGIN = "http://localhost:3000";

function request(
  path: string,
  cookies: Record<string, string> = {},
  init?: ConstructorParameters<typeof NextRequest>[1],
) {
  const req = new NextRequest(`${ORIGIN}${path}`, init);
  for (const [k, v] of Object.entries(cookies)) req.cookies.set(k, v);
  return req;
}

const cookieValue = (res: Response, name: string) =>
  res.headers
    .getSetCookie()
    .find((c) => c.startsWith(`${name}=`))
    ?.split(";")[0]
    .slice(name.length + 1);

const account = (overrides = {}) =>
  seal(
    {
      id: "acct-1",
      email: "ana@x.com",
      name: "Ana",
      avatarUrl: null,
      isAdmin: false,
      expiresAt: Date.now() + 60_000,
      ...overrides,
    },
    sessionKey()!,
  );

function mockGoogle({ verified = true, service = 200, blocked = false } = {}) {
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: init?.body ? String(init.body) : undefined });
      if (url === "https://oauth2.googleapis.com/token") return Response.json({ access_token: "ya29.x" });
      if (url.startsWith("https://openidconnect.googleapis.com")) {
        return Response.json({
          sub: "g-1",
          email: "ana@x.com",
          email_verified: verified,
          name: "Ana",
          picture: "p.png",
        });
      }
      if (url.endsWith("/auth/sign-in")) {
        return service === 200
          ? Response.json({ id: "acct-1", email: "ana@x.com", name: "Ana", avatar_url: "p.png", is_admin: true })
          : Response.json({ detail: "no", ...(blocked ? { code: "blocked" } : {}) }, { status: service });
      }
      return Response.json({ threads: [] });
    }),
  );
  return calls;
}

async function startLogin(returnTo = "/chat/chatbot/t1") {
  const res = login(request(`/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`));
  const google = new URL(res.headers.get("location")!);
  return { google, cookie: cookieValue(res, SIGN_IN_COOKIE)! };
}

beforeEach(() => {
  vi.stubEnv("AUTH_ENABLED", "true");
  vi.stubEnv("GOOGLE_CLIENT_ID", "client.apps.googleusercontent.com");
  vi.stubEnv("GOOGLE_CLIENT_SECRET", "google-secret");
  vi.stubEnv("WEB_SESSION_SECRET", "session-secret");
  vi.stubEnv("AGENT_URL", "http://agent:8080");
  vi.stubEnv("AUTH_SECRET", "service-secret");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Google sign-in", () => {
  it("sends the browser to Google with PKCE and a state", async () => {
    const { google } = await startLogin();
    expect(google.origin + google.pathname).toBe("https://accounts.google.com/o/oauth2/v2/auth");
    expect(google.searchParams.get("scope")).toBe("openid email profile");
    expect(google.searchParams.get("code_challenge_method")).toBe("S256");
    expect(google.searchParams.get("redirect_uri")).toBe(`${ORIGIN}/api/auth/callback`);
    expect(google.searchParams.get("state")).toBeTruthy();
  });

  it("falls back to this site's callback when GOOGLE_REDIRECT_URI is empty", async () => {
    vi.stubEnv("GOOGLE_REDIRECT_URI", "");
    const { google } = await startLogin();
    expect(google.searchParams.get("redirect_uri")).toBe(`${ORIGIN}/api/auth/callback`);
  });

  it("signs in, hands over the anonymous id and returns to the page", async () => {
    const calls = mockGoogle();
    const { google, cookie } = await startLogin();
    const res = await callback(
      request(`/api/auth/callback?code=c1&state=${google.searchParams.get("state")}`, {
        [SIGN_IN_COOKIE]: cookie,
        uid: "anon-7",
      }),
    );
    expect(res.headers.get("location")).toBe(`${ORIGIN}/chat/chatbot/t1`);
    const session = readAccount({ cookies: { get: () => ({ value: cookieValue(res, ACCOUNT_COOKIE)! }) } } as never);
    expect(session).toMatchObject({ id: "acct-1", email: "ana@x.com", isAdmin: true });

    const signIn = calls.find((c) => c.url === "http://agent:8080/auth/sign-in")!;
    expect(JSON.parse(signIn.body!)).toMatchObject({
      google_sub: "g-1",
      email_verified: true,
      anonymous_user_id: "anon-7",
    });
    expect(calls[0].body).toContain("code_verifier=");
  });

  it.each([
    ["a wrong state", { state: "forged" }, "expired"],
    ["an unverified email", { verified: false }, "unverified"],
    ["sign-ups that don't allow the email", { service: 403 }, "not_allowed"],
    ["a service failure", { service: 500 }, "failed"],
    ["a blocked account", { service: 403, blocked: true }, "blocked"],
  ])("sends %s back to the login page", async (_, opts, error) => {
    mockGoogle(opts as { verified?: boolean; service?: number; blocked?: boolean });
    const { google, cookie } = await startLogin();
    const state = (opts as { state?: string }).state ?? google.searchParams.get("state");
    const res = await callback(request(`/api/auth/callback?code=c1&state=${state}`, { [SIGN_IN_COOKIE]: cookie }));
    expect(res.headers.get("location")).toBe(`${ORIGIN}/login?error=${error}`);
    expect(cookieValue(res, ACCOUNT_COOKIE)).toBeFalsy();
  });

  it("reports the signed-in account and treats expired sessions as signed out", async () => {
    expect(await me(request("/api/auth/me", { [ACCOUNT_COOKIE]: account() })).json()).toMatchObject({
      enabled: true,
      account: { email: "ana@x.com", is_admin: false },
    });
    const expired = account({ expiresAt: Date.now() - 1 });
    expect((await me(request("/api/auth/me", { [ACCOUNT_COOKIE]: expired })).json()).account).toBeNull();
  });
});

describe("with sign-in on", () => {
  it("refuses API calls without an account and never forwards them", async () => {
    const calls = mockGoogle();
    const res = await agentGet(request("/api/agent/chats", { uid: "anon-1" }), {
      params: Promise.resolve({ path: ["chats"] }),
    });
    expect(res.status).toBe(401);
    expect((await res.json()).code).toBe("auth_required");
    expect(calls).toHaveLength(0);
  });

  it("acts as the account, not the anonymous browser id", async () => {
    const calls = mockGoogle();
    const req = request(
      "/api/agent/chatbot/stream",
      { uid: "anon-1", [ACCOUNT_COOKIE]: account() },
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ message: "hi" }) },
    );
    await agentPost(req, { params: Promise.resolve({ path: ["chatbot", "stream"] }) });
    expect(JSON.parse(calls[0].body!).user_id).toBe("acct-1");
  });

  it("sends signed-out pages to the login page and signed-in users away from it", () => {
    const out = proxy(request("/library?x=1"));
    const to = new URL(out.headers.get("location")!);
    expect(to.pathname).toBe("/login");
    expect(to.searchParams.get("returnTo")).toBe("/library?x=1");

    expect(proxy(request("/login")).headers.get("location")).toBeNull();
    expect(proxy(request("/login", { [ACCOUNT_COOKIE]: account() })).headers.get("location")).toBe(`${ORIGIN}/`);
    expect(proxy(request("/", { [ACCOUNT_COOKIE]: account() })).headers.get("location")).toBeNull();
  });

  it("leaves everything open when sign-in is off", async () => {
    vi.stubEnv("AUTH_ENABLED", "false");
    expect(proxy(request("/library")).headers.get("location")).toBeNull();
    const calls = mockGoogle();
    const res = await agentGet(request("/api/agent/chats", { uid: "anon-1" }), {
      params: Promise.resolve({ path: ["chats"] }),
    });
    expect(res.status).toBe(200);
    expect(new URL(calls[0].url).searchParams.get("user_id")).toBe("anon-1");
  });
});
