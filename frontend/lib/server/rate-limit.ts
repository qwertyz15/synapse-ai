/**
 * In-memory sliding-window limits for the agent proxy. They hold per server process, which is
 * the supported single-instance setup; several web replicas would each keep their own counts.
 */

export type Limit = { max: number; windowMs: number };
export type Kind = "chat" | "upload";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const MAX_TRACKED_KEYS = 50_000;

const envInt = (name: string, fallback: number) => {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
};

/** Limits per browser user; an IP gets three times as much since users can share one (NAT, offices). */
export function limitsFor(kind: Kind): { user: Limit; ip: Limit; global?: Limit } {
  if (kind === "chat") {
    const perHour = envInt("RATE_LIMIT_CHATS_PER_HOUR", 60);
    return {
      user: { max: perHour, windowMs: HOUR },
      ip: { max: perHour * 3, windowMs: HOUR },
      global: { max: envInt("RATE_LIMIT_CHATS_PER_MINUTE_GLOBAL", 120), windowMs: MINUTE },
    };
  }
  const perHour = envInt("RATE_LIMIT_UPLOADS_PER_HOUR", 20);
  return { user: { max: perHour, windowMs: HOUR }, ip: { max: perHour * 3, windowMs: HOUR } };
}

export class RateLimiter {
  private hits = new Map<string, number[]>();

  /** Seconds to wait before `key` may proceed, or 0 if it can (and the attempt is counted). */
  check(entries: [key: string, limit: Limit][], now = Date.now()): number {
    let wait = 0;
    for (const [key, { max, windowMs }] of entries) {
      if (max === 0) continue;
      const recent = (this.hits.get(key) ?? []).filter((t) => t > now - windowMs);
      this.hits.set(key, recent);
      if (recent.length >= max) wait = Math.max(wait, Math.ceil((recent[0] + windowMs - now) / 1000));
    }
    if (wait > 0) return wait;
    for (const [key, { max }] of entries) if (max !== 0) this.hits.get(key)!.push(now);
    if (this.hits.size > MAX_TRACKED_KEYS) this.prune(now);
    return 0;
  }

  private prune(now: number) {
    for (const [key, times] of this.hits)
      if (!times.length || times[times.length - 1] < now - 24 * HOUR) this.hits.delete(key);
  }
}

/** The address the closest proxy saw. Only trustworthy behind a reverse proxy that sets X-Forwarded-For. */
export function clientIp(headers: Headers): string {
  const hops = (headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((h) => h.trim())
    .filter(Boolean);
  return hops.at(-1) ?? headers.get("x-real-ip") ?? "unknown";
}
