import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET as callback } from "../callback/route";
import { GET as install } from "../install/route";
import { GET as login } from "../login/route";
import { OAUTH_COOKIE, SESSION_COOKIE, githubConfig, seal, type GithubSession } from "@/lib/server/github-session";

const ORIGIN = "http://localhost:3000";

function request(path: string, cookies: Record<string, string> = {}) {
  const req = new NextRequest(`${ORIGIN}${path}`);
  for (const [k, v] of Object.entries(cookies)) req.cookies.set(k, v);
  return req;
}

const cookieValue = (res: Response, name: string) =>
  res.headers
    .getSetCookie()
    .find((c) => c.startsWith(`${name}=`))
    ?.split(";")[0]
    .slice(name.length + 1);

function mockGithub(installations: number) {
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, body: init?.body ? String(init.body) : undefined });
      if (url.endsWith("/login/oauth/access_token")) {
        return Response.json({ access_token: "ghu_new", expires_in: 28800, refresh_token: "ghr_new" });
      }
      if (url.endsWith("/user")) return Response.json({ login: "octo", avatar_url: "https://x/a.png" });
      if (url.includes("/user/installations")) return Response.json({ total_count: installations });
      return new Response("unexpected", { status: 500 });
    }),
  );
  return calls;
}

async function startLogin() {
  const res = login(request("/api/github/login?returnTo=/chat/x"));
  const state = new URL(res.headers.get("location")!).searchParams.get("state")!;
  return { state, oauthCookie: cookieValue(res, OAUTH_COOKIE)! };
}

beforeEach(() => {
  vi.stubEnv("GITHUB_CLIENT_ID", "Iv_test");
  vi.stubEnv("GITHUB_CLIENT_SECRET", "secret");
  vi.stubEnv("WEB_SESSION_SECRET", "session-secret");
  vi.stubEnv("GITHUB_APP_SLUG", "my-app");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("GitHub callback", () => {
  it("chains into the install page when the app isn't installed yet", async () => {
    mockGithub(0);
    const { state, oauthCookie } = await startLogin();
    const res = await callback(request(`/api/github/callback?code=c1&state=${state}`, { [OAUTH_COOKIE]: oauthCookie }));
    const location = new URL(res.headers.get("location")!);
    expect(location.origin + location.pathname).toBe("https://github.com/apps/my-app/installations/new");
    expect(location.searchParams.get("state")).not.toBe(state);
    expect(cookieValue(res, SESSION_COOKIE)).toBeTruthy();
    expect(cookieValue(res, OAUTH_COOKIE)).toBeTruthy();
  });

  it("returns straight to the chat when the app is already installed", async () => {
    mockGithub(2);
    const { state, oauthCookie } = await startLogin();
    const res = await callback(request(`/api/github/callback?code=c1&state=${state}`, { [OAUTH_COOKIE]: oauthCookie }));
    expect(res.headers.get("location")).toBe(`${ORIGIN}/chat/x?github=connected`);
  });

  it("finishes the install leg without PKCE and keeps the return path", async () => {
    const calls = mockGithub(1);
    const res0 = install(request("/api/github/install?returnTo=/chat/x"));
    const state = new URL(res0.headers.get("location")!).searchParams.get("state")!;
    const res = await callback(
      request(`/api/github/callback?code=c2&installation_id=9&setup_action=install&state=${state}`, {
        [OAUTH_COOKIE]: cookieValue(res0, OAUTH_COOKIE)!,
      }),
    );
    expect(res.headers.get("location")).toBe(`${ORIGIN}/chat/x?github=connected`);
    const exchange = calls.find((c) => c.url.endsWith("/access_token"))!;
    expect(exchange.body).not.toContain("code_verifier");
  });

  it("accepts an install finished on GitHub's own pages when already connected", async () => {
    mockGithub(1);
    const key = githubConfig()!.key;
    const session: GithubSession = { accessToken: "ghu_old", login: "octo", avatarUrl: "" };
    const res = await callback(
      request("/api/github/callback?installation_id=9&setup_action=update", { [SESSION_COOKIE]: seal(session, key) }),
    );
    expect(res.headers.get("location")).toBe(`${ORIGIN}/?github=connected`);
  });

  it("rejects a forged callback", async () => {
    mockGithub(1);
    const res = await callback(request("/api/github/callback?code=c1&state=forged"));
    expect(res.headers.get("location")).toBe(`${ORIGIN}/?github=error&reason=invalid_state`);
    expect(cookieValue(res, SESSION_COOKIE)).toBeUndefined();
  });
});
