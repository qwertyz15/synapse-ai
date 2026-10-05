import { createHash } from "node:crypto";

import { describe, expect, it } from "vitest";

import { canRefresh, needsRefresh, pkceChallenge, seal, unseal, type GithubSession } from "../github-session";

const key = createHash("sha256").update("test-secret").digest();
const otherKey = createHash("sha256").update("other-secret").digest();
const session: GithubSession = { accessToken: "ghu_abc", refreshToken: "ghr_def", login: "octo", avatarUrl: "" };

describe("seal/unseal", () => {
  it("round-trips and hides the token", () => {
    const sealed = seal(session, key);
    expect(sealed).not.toContain("ghu_abc");
    expect(unseal(sealed, key)).toEqual(session);
  });

  it("rejects tampering, wrong keys and garbage", () => {
    const sealed = seal(session, key);
    const flipped = sealed.slice(0, -2) + (sealed.endsWith("A") ? "BB" : "AA");
    expect(unseal(flipped, key)).toBeNull();
    expect(unseal(sealed, otherKey)).toBeNull();
    expect(unseal("not-a-cookie", key)).toBeNull();
    expect(unseal(undefined, key)).toBeNull();
  });

  it("uses a fresh IV each time", () => {
    expect(seal(session, key)).not.toEqual(seal(session, key));
  });
});

describe("token lifetime", () => {
  const now = 1_000_000;

  it("refreshes shortly before expiry and never for non-expiring tokens", () => {
    expect(needsRefresh({ ...session, expiresAt: now + 30_000 }, now)).toBe(true);
    expect(needsRefresh({ ...session, expiresAt: now + 10 * 60_000 }, now)).toBe(false);
    expect(needsRefresh({ ...session, expiresAt: undefined }, now)).toBe(false);
  });

  it("only refreshes with a live refresh token", () => {
    expect(canRefresh({ ...session, refreshExpiresAt: now + 1 }, now)).toBe(true);
    expect(canRefresh({ ...session, refreshExpiresAt: now - 1 }, now)).toBe(false);
    expect(canRefresh({ ...session, refreshToken: undefined }, now)).toBe(false);
  });
});

it("builds an RFC 7636 S256 challenge", () => {
  expect(pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe(
    "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
  );
});
