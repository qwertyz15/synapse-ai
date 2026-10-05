import { NextRequest, NextResponse } from "next/server";

import { GITHUB_AGENT, USER_COOKIE } from "@/lib/constants";
import { clearSession, resolveSession, writeSession, type GithubSession } from "@/lib/server/github-session";

export const dynamic = "force-dynamic";

const AGENT_URL = (process.env.AGENT_URL ?? "http://localhost:8080").replace(/\/$/, "");
const AGENT = "[a-z0-9][a-z0-9_-]*";

const ROUTES: { method: string; pattern: RegExp; userId?: "body" | "query" }[] = [
  { method: "GET", pattern: /^info$/ },
  { method: "POST", pattern: new RegExp(`^${AGENT}/stream$`), userId: "body" },
  { method: "POST", pattern: new RegExp(`^${AGENT}/history$`) },
  { method: "GET", pattern: new RegExp(`^${AGENT}/threads$`), userId: "query" },
  { method: "POST", pattern: /^feedback$/ },
  { method: "GET", pattern: /^rag\/documents$/ },
  { method: "POST", pattern: /^rag\/documents$/ },
  { method: "DELETE", pattern: /^rag\/documents\/.+$/ },
];

async function forward(req: NextRequest, ctx: RouteContext<"/api/agent/[...path]">) {
  const segments = (await ctx.params).path;
  const path = segments.map(encodeURIComponent).join("/");
  const route = ROUTES.find((r) => r.method === req.method && r.pattern.test(segments.join("/")));
  if (!route) return NextResponse.json({ detail: "Not found" }, { status: 404 });

  const existingUid = req.cookies.get(USER_COOKIE)?.value;
  const uid = existingUid ?? crypto.randomUUID();

  const url = new URL(`${AGENT_URL}/${path}`);
  req.nextUrl.searchParams.forEach((value, key) => url.searchParams.set(key, value));
  if (route.userId === "query") url.searchParams.set("user_id", uid);

  const headers = new Headers();
  if (process.env.AUTH_SECRET) headers.set("Authorization", `Bearer ${process.env.AUTH_SECRET}`);

  let github: { session: GithubSession | null; updated: boolean; cleared: boolean } | null = null;
  if (route.userId === "body" && segments[0] === GITHUB_AGENT) {
    github = await resolveSession(req);
    if (!github.session) {
      const res = NextResponse.json(
        { detail: "Connect your GitHub account to use this agent.", code: "github_not_connected" },
        { status: 401 },
      );
      if (github.cleared) clearSession(res, req);
      return res;
    }
    headers.set("X-GitHub-Token", github.session.accessToken);
  }

  let body: BodyInit | undefined;
  if (req.method === "POST") {
    const contentType = req.headers.get("content-type") ?? "";
    headers.set("Content-Type", contentType);
    if (route.userId === "body") {
      const json = await req.json();
      body = JSON.stringify({ ...json, user_id: uid });
    } else {
      body = await req.arrayBuffer();
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, { method: req.method, headers, body, signal: req.signal, cache: "no-store" });
  } catch (err) {
    if (req.signal.aborted) return new Response(null, { status: 499 });
    console.error("Agent service unreachable:", err);
    return NextResponse.json({ detail: `Agent service unreachable at ${AGENT_URL}` }, { status: 502 });
  }

  const res = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
  if (github?.session && github.updated) writeSession(res, req, github.session);
  if (!existingUid) {
    res.cookies.set(USER_COOKIE, uid, { httpOnly: true, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 400 });
  }
  return res;
}

export { forward as GET, forward as POST, forward as DELETE };
