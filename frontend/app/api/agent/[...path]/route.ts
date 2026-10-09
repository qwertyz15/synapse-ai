import { NextRequest, NextResponse } from "next/server";

import { GITHUB_AGENT, USER_COOKIE } from "@/lib/constants";
import { clearSession, resolveSession, writeSession, type GithubSession } from "@/lib/server/github-session";
import { RateLimiter, clientIp, limitsFor, type Kind, type Limit } from "@/lib/server/rate-limit";

export const dynamic = "force-dynamic";

const AGENT_URL = (process.env.AGENT_URL ?? "http://localhost:8080").replace(/\/$/, "");
const AGENT = "[a-z0-9][a-z0-9_-]*";
const MB = 1024 * 1024;
const DEFAULT_MAX_BYTES = MB;
const limiter = new RateLimiter();

type Route = { method: string; pattern: RegExp; userId?: "body" | "query"; limit?: Kind; maxBytes?: number };

const ROUTES: Route[] = [
  { method: "GET", pattern: /^info$/ },
  { method: "POST", pattern: new RegExp(`^${AGENT}/stream$`), userId: "body", limit: "chat", maxBytes: 256 * 1024 },
  { method: "POST", pattern: new RegExp(`^${AGENT}/history$`), userId: "body" },
  { method: "GET", pattern: new RegExp(`^${AGENT}/threads$`), userId: "query" },
  { method: "GET", pattern: /^chats$/, userId: "query" },
  { method: "DELETE", pattern: new RegExp(`^${AGENT}/threads/[^/]+$`), userId: "query" },
  { method: "POST", pattern: /^feedback$/ },
  { method: "GET", pattern: /^rag\/my-documents$/, userId: "query" },
  { method: "POST", pattern: /^rag\/my-documents$/, userId: "query", limit: "upload", maxBytes: 60 * MB },
  { method: "DELETE", pattern: /^rag\/my-documents\/[^/]+$/, userId: "query" },
  { method: "GET", pattern: /^rag\/attachments$/, userId: "query" },
  { method: "POST", pattern: /^rag\/attachments$/, userId: "query", limit: "upload", maxBytes: 60 * MB },
  { method: "DELETE", pattern: /^rag\/attachments\/.+$/, userId: "query" },
];

const tooLarge = () => NextResponse.json({ detail: "This request is too large." }, { status: 413 });

/** The request body, or null once it passes `max` bytes (Content-Length alone can be left out). */
async function readLimited(req: NextRequest, max: number): Promise<Uint8Array<ArrayBuffer> | null> {
  if (!req.body) return new Uint8Array();
  const reader = req.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel();
      return null;
    }
    parts.push(value);
  }
  const out = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.byteLength;
  }
  return out;
}

async function forward(req: NextRequest, ctx: RouteContext<"/api/agent/[...path]">) {
  const segments = (await ctx.params).path;
  const path = segments.map(encodeURIComponent).join("/");
  const route = ROUTES.find((r) => r.method === req.method && r.pattern.test(segments.join("/")));
  if (!route) return NextResponse.json({ detail: "Not found" }, { status: 404 });

  const existingUid = req.cookies.get(USER_COOKIE)?.value;
  const uid = existingUid ?? crypto.randomUUID();

  const maxBytes = route.maxBytes ?? DEFAULT_MAX_BYTES;
  if (Number(req.headers.get("content-length") ?? 0) > maxBytes) return tooLarge();
  if (route.limit) {
    const limits = limitsFor(route.limit);
    const entries: [string, Limit][] = [
      [`${route.limit}:user:${uid}`, limits.user],
      [`${route.limit}:ip:${clientIp(req.headers)}`, limits.ip],
    ];
    if (limits.global) entries.push([`${route.limit}:global`, limits.global]);
    const wait = limiter.check(entries);
    if (wait > 0) {
      const minutes = Math.ceil(wait / 60);
      return NextResponse.json(
        { detail: `Too many requests. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.` },
        { status: 429, headers: { "Retry-After": String(wait) } },
      );
    }
  }

  const url = new URL(`${AGENT_URL}/${path}`);
  req.nextUrl.searchParams.forEach((value, key) => url.searchParams.set(key, value));
  if (route.userId === "query") url.searchParams.set("user_id", uid);

  const headers = new Headers();
  if (process.env.AUTH_SECRET) headers.set("Authorization", `Bearer ${process.env.AUTH_SECRET}`);

  let body: BodyInit | undefined;
  let wantsGithub = false;
  let githubWrite = false;
  if (req.method === "POST") {
    const contentType = req.headers.get("content-type") ?? "";
    headers.set("Content-Type", contentType);
    const raw = await readLimited(req, maxBytes);
    if (!raw) return tooLarge();
    if (route.userId === "body") {
      const { connectors, github_write, ...json } = JSON.parse(new TextDecoder().decode(raw));
      wantsGithub = segments[0] === GITHUB_AGENT || (Array.isArray(connectors) && connectors.includes("github"));
      githubWrite = github_write === true;
      body = JSON.stringify({ ...json, user_id: uid });
    } else {
      body = raw;
    }
  }

  // GitHub credentials are only forwarded for runs that asked for the GitHub connector.
  let github: { session: GithubSession | null; updated: boolean; cleared: boolean } | null = null;
  if (wantsGithub) {
    github = await resolveSession(req);
    if (!github.session) {
      const res = NextResponse.json(
        { detail: "Connect your GitHub account to use GitHub in this chat.", code: "github_not_connected" },
        { status: 401 },
      );
      if (github.cleared) clearSession(res, req);
      return res;
    }
    headers.set("X-GitHub-Token", github.session.accessToken);
    headers.set("X-GitHub-Login", github.session.login);
    headers.set("X-GitHub-Write", githubWrite ? "true" : "false");
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
