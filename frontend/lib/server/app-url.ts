import type { NextRequest } from "next/server";

// In route handlers req.url carries the listen address (0.0.0.0:3000 in Docker), not the host the
// browser used, so redirects built from it land on a host without the browser's cookies.
export function appUrl(path: string, req: NextRequest): URL {
  const host = req.headers.get("x-forwarded-host")?.split(",")[0].trim() || req.headers.get("host");
  if (!host) return new URL(path, req.url);
  const proto =
    req.headers.get("x-forwarded-proto")?.split(",")[0].trim() || req.nextUrl.protocol.replace(/:$/, "");
  return new URL(path, `${proto}://${host}`);
}
