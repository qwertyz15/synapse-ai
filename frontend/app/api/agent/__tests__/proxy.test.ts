import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET, POST } from "../[...path]/route";
import { SESSION_COOKIE, githubConfig, seal, type GithubSession } from "@/lib/server/github-session";

type Sent = { url: string; headers: Headers; body: Record<string, unknown> };

function mockService() {
  const sent: Sent[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL, init?: RequestInit) => {
      sent.push({ url: String(input), headers: new Headers(init?.headers), body: JSON.parse(String(init?.body)) });
      return new Response("data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } });
    }),
  );
  return sent;
}

function stream(agent: string, body: Record<string, unknown>, session?: GithubSession) {
  const req = new NextRequest(`http://localhost:3000/api/agent/${agent}/stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message: "hi", thread_id: "t", ...body }),
  });
  req.cookies.set("uid", "browser-1");
  if (session) req.cookies.set(SESSION_COOKIE, seal(session, githubConfig()!.key));
  return POST(req, { params: Promise.resolve({ path: [agent, "stream"] }) });
}

const session: GithubSession = { accessToken: "ghu_user", login: "octo", avatarUrl: "" };

beforeEach(() => {
  vi.stubEnv("GITHUB_CLIENT_ID", "Iv_test");
  vi.stubEnv("GITHUB_CLIENT_SECRET", "secret");
  vi.stubEnv("WEB_SESSION_SECRET", "session-secret");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("agent proxy GitHub connector", () => {
  it("sends no GitHub credentials without the connector, even when connected", async () => {
    const sent = mockService();
    const res = await stream("research-assistant", { connectors: [] }, session);
    expect(res.status).toBe(200);
    expect(sent[0].headers.has("X-GitHub-Token")).toBe(false);
    expect(sent[0].body).not.toHaveProperty("connectors");
    expect(sent[0].body.user_id).toBe("browser-1");
  });

  it("asks to connect when the connector is on but GitHub isn't connected", async () => {
    const sent = mockService();
    const res = await stream("research-assistant", { connectors: ["github"] });
    expect(res.status).toBe(401);
    expect((await res.json()).code).toBe("github_not_connected");
    expect(sent).toHaveLength(0);
  });

  it("forwards token, login and write flag, stripping connector fields", async () => {
    const sent = mockService();
    await stream("research-assistant", { connectors: ["github"], github_write: true }, session);
    const { headers, body } = sent[0];
    expect(headers.get("X-GitHub-Token")).toBe("ghu_user");
    expect(headers.get("X-GitHub-Login")).toBe("octo");
    expect(headers.get("X-GitHub-Write")).toBe("true");
    expect(body).not.toHaveProperty("connectors");
    expect(body).not.toHaveProperty("github_write");
  });

  it("defaults to read-only", async () => {
    const sent = mockService();
    await stream("research-assistant", { connectors: ["github"] }, session);
    expect(sent[0].headers.get("X-GitHub-Write")).toBe("false");
  });
});

it("scopes chat attachment requests to the browser's user id", async () => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL) => {
      urls.push(String(input));
      return Response.json({ attachments: [] });
    }),
  );
  const req = new NextRequest("http://localhost:3000/api/agent/rag/attachments?thread_id=t1&user_id=spoofed");
  req.cookies.set("uid", "browser-1");
  await GET(req, { params: Promise.resolve({ path: ["rag", "attachments"] }) });
  const sent = new URL(urls[0]);
  expect(sent.pathname).toBe("/rag/attachments");
  expect(sent.searchParams.get("thread_id")).toBe("t1");
  expect(sent.searchParams.get("user_id")).toBe("browser-1");
});

it("lists every chat with one request scoped to the browser's user", async () => {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL) => {
      urls.push(String(input));
      return Response.json({ threads: [] });
    }),
  );
  const req = new NextRequest("http://localhost:3000/api/agent/chats?limit=100&user_id=spoofed");
  req.cookies.set("uid", "browser-1");
  const res = await GET(req, { params: Promise.resolve({ path: ["chats"] }) });
  expect(res.status).toBe(200);
  const sent = new URL(urls[0]);
  expect(sent.pathname).toBe("/chats");
  expect(sent.searchParams.get("user_id")).toBe("browser-1");
});
