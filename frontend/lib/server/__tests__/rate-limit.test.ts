import { afterEach, describe, expect, it, vi } from "vitest";

import { RateLimiter, clientIp, limitsFor } from "../rate-limit";

const MINUTE = 60_000;

afterEach(() => vi.unstubAllEnvs());

describe("RateLimiter", () => {
  it("allows up to the limit, then says how long to wait", () => {
    const limiter = new RateLimiter();
    const limit = { max: 2, windowMs: MINUTE };
    expect(limiter.check([["u", limit]], 0)).toBe(0);
    expect(limiter.check([["u", limit]], 1_000)).toBe(0);
    expect(limiter.check([["u", limit]], 2_000)).toBe(58);
    expect(limiter.check([["u", limit]], MINUTE + 1)).toBe(0);
  });

  it("blocks when any key is over and doesn't count the blocked attempt", () => {
    const limiter = new RateLimiter();
    const one = { max: 1, windowMs: MINUTE };
    const many = { max: 10, windowMs: MINUTE };
    limiter.check([["ip", one]], 0);
    expect(
      limiter.check(
        [
          ["user", many],
          ["ip", one],
        ],
        1,
      ),
    ).toBeGreaterThan(0);
    for (let i = 0; i < 10; i++) expect(limiter.check([["user", many]], 2 + i)).toBe(0);
  });

  it("treats a limit of 0 as off", () => {
    const limiter = new RateLimiter();
    for (let i = 0; i < 100; i++) expect(limiter.check([["u", { max: 0, windowMs: MINUTE }]], i)).toBe(0);
  });
});

describe("limitsFor", () => {
  it("reads limits from the environment", () => {
    vi.stubEnv("RATE_LIMIT_CHATS_PER_HOUR", "5");
    expect(limitsFor("chat").user.max).toBe(5);
    expect(limitsFor("chat").ip.max).toBe(15);
    expect(limitsFor("upload").user.max).toBe(20);
  });
});

describe("clientIp", () => {
  it("uses the hop added by the closest proxy", () => {
    expect(clientIp(new Headers({ "x-forwarded-for": "6.6.6.6, 10.0.0.1, 203.0.113.9" }))).toBe("203.0.113.9");
    expect(clientIp(new Headers({ "x-real-ip": "198.51.100.2" }))).toBe("198.51.100.2");
    expect(clientIp(new Headers())).toBe("unknown");
  });
});
