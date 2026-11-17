import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { appUrl } from "@/lib/server/app-url";

describe("appUrl", () => {
  it("uses the Host header, not the listen address", () => {
    const req = new NextRequest("http://0.0.0.0:3000/api/auth/callback", { headers: { host: "localhost:3000" } });
    expect(appUrl("/chat/x", req).toString()).toBe("http://localhost:3000/chat/x");
  });

  it("prefers forwarded host and protocol behind a reverse proxy", () => {
    const req = new NextRequest("http://0.0.0.0:3000/api/auth/callback", {
      headers: { host: "web:3000", "x-forwarded-host": "chat.example.com", "x-forwarded-proto": "https" },
    });
    expect(appUrl("/login?error=expired", req).toString()).toBe("https://chat.example.com/login?error=expired");
  });

  it("falls back to the request URL without a Host header", () => {
    const req = new NextRequest("http://localhost:3000/api/auth/login");
    expect(appUrl("/", req).toString()).toBe("http://localhost:3000/");
  });
});
