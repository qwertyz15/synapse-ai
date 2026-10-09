import "server-only";

import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

import type { NextRequest } from "next/server";

/** AES-256-GCM key for sealed cookies, from WEB_SESSION_SECRET; null when it isn't set. */
export function sessionKey(): Buffer | null {
  const secret = process.env.WEB_SESSION_SECRET;
  return secret ? createHash("sha256").update(secret).digest() : null;
}

export function seal(value: unknown, key: Buffer): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const body = Buffer.concat([cipher.update(JSON.stringify(value), "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString("base64url");
}

export function unseal<T>(sealed: string | undefined, key: Buffer): T | null {
  if (!sealed) return null;
  try {
    const raw = Buffer.from(sealed, "base64url");
    const decipher = createDecipheriv("aes-256-gcm", key, raw.subarray(0, 12));
    decipher.setAuthTag(raw.subarray(12, 28));
    const text = Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]).toString("utf8");
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export const randomToken = () => randomBytes(32).toString("base64url");

/** A same-site path to return to after GitHub; anything that resolves to another origin becomes "/". */
export function safeReturnTo(requested: string | null | undefined): string {
  const base = "http://same.invalid";
  try {
    const url = new URL(requested || "/", base);
    return url.origin === base ? `${url.pathname}${url.search}${url.hash}` : "/";
  } catch {
    return "/";
  }
}

export const pkceChallenge = (verifier: string) => createHash("sha256").update(verifier).digest("base64url");

export const cookieOptions = (req: NextRequest, maxAge: number) => ({
  httpOnly: true,
  sameSite: "lax" as const,
  secure: req.nextUrl.protocol === "https:",
  path: "/",
  maxAge,
});
