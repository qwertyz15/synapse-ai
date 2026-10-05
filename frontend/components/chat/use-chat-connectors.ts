"use client";

import { useCallback, useEffect, useState } from "react";

import type { Connector } from "@/lib/agents";

const key = (threadId: string) => `ui.connectors:${threadId}`;
// Survives the GitHub sign-in redirect, which lands on a fresh chat page.
const PENDING_KEY = "ui.connectors:pending";

export type ChatConnectors = {
  connectors: Connector[];
  toggle: (connector: Connector, on: boolean) => void;
  /** Turn a connector on after an OAuth round trip that reloads the page. */
  enableAfterRedirect: (connector: Connector) => void;
};

function read(storage: () => Storage, k: string): string | null {
  try {
    return storage().getItem(k);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, k: string, value: string | null) {
  try {
    if (value === null) storage().removeItem(k);
    else storage().setItem(k, value);
  } catch {}
}

const local = () => localStorage;
const session = () => sessionStorage;
const parse = (raw: string | null): Connector[] => (raw ? (raw.split(",").filter(Boolean) as Connector[]) : []);

/** Connectors are chosen per chat: a new chat starts with none, and each chat remembers its own. */
export function useChatConnectors(threadId: string): ChatConnectors {
  const [connectors, setConnectors] = useState<Connector[]>([]);

  useEffect(() => {
    const saved = parse(read(local, key(threadId)));
    const pending = parse(read(session, PENDING_KEY));
    write(session, PENDING_KEY, null);
    const restored = [...new Set([...saved, ...pending])];
    if (pending.length) write(local, key(threadId), restored.join(","));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a per-browser preference after hydration
    setConnectors(restored);
  }, [threadId]);

  const toggle = useCallback(
    (connector: Connector, on: boolean) => {
      setConnectors((current) => {
        const next = on ? [...new Set([...current, connector])] : current.filter((c) => c !== connector);
        write(local, key(threadId), next.length ? next.join(",") : null);
        return next;
      });
    },
    [threadId],
  );

  const enableAfterRedirect = useCallback((connector: Connector) => write(session, PENDING_KEY, connector), []);

  return { connectors, toggle, enableAfterRedirect };
}
