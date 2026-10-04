"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { getAllThreads, getInfo } from "@/lib/api";
import type { ServiceMetadata, ThreadInfo } from "@/lib/types";

type AppState = {
  info: ServiceMetadata | null;
  infoError: string | null;
  retryInfo: () => void;
  agent: string;
  setAgent: (agent: string) => void;
  model: string;
  setModel: (model: string) => void;
  threads: ThreadInfo[] | null;
  refreshThreads: () => void;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  mobileNavOpen: boolean;
  setMobileNavOpen: (open: boolean) => void;
};

const AppContext = createContext<AppState | null>(null);

const STORAGE_AGENT = "ui.agent";
const STORAGE_MODEL = "ui.model";
const STORAGE_SIDEBAR = "ui.sidebar";

function load(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {}
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [info, setInfo] = useState<ServiceMetadata | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [infoAttempt, setInfoAttempt] = useState(0);
  const [agent, setAgentState] = useState("");
  const [model, setModelState] = useState("");
  const [threads, setThreads] = useState<ThreadInfo[] | null>(null);
  const [sidebarOpen, setSidebarOpenState] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a per-browser preference after hydration
    setSidebarOpenState(load(STORAGE_SIDEBAR) !== "closed");
  }, []);

  useEffect(() => {
    let cancelled = false;
    getInfo()
      .then((meta) => {
        if (cancelled) return;
        setInfo(meta);
        setInfoError(null);
        const savedAgent = load(STORAGE_AGENT);
        const savedModel = load(STORAGE_MODEL);
        setAgentState(
          (current) =>
            current || (savedAgent && meta.agents.some((a) => a.key === savedAgent) ? savedAgent : meta.default_agent),
        );
        setModelState(savedModel && meta.models.includes(savedModel) ? savedModel : meta.default_model);
      })
      .catch((err: Error) => !cancelled && setInfoError(err.message));
    return () => {
      cancelled = true;
    };
  }, [infoAttempt]);

  const refreshThreads = useCallback(() => {
    if (!info) return;
    getAllThreads(info.agents.map((a) => a.key)).then(setThreads);
  }, [info]);

  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  const value = useMemo<AppState>(
    () => ({
      info,
      infoError,
      retryInfo: () => setInfoAttempt((n) => n + 1),
      agent,
      setAgent: (a) => {
        setAgentState(a);
        save(STORAGE_AGENT, a);
      },
      model,
      setModel: (m) => {
        setModelState(m);
        save(STORAGE_MODEL, m);
      },
      threads,
      refreshThreads,
      sidebarOpen,
      setSidebarOpen: (open) => {
        setSidebarOpenState(open);
        save(STORAGE_SIDEBAR, open ? "open" : "closed");
      },
      mobileNavOpen,
      setMobileNavOpen,
    }),
    [info, infoError, agent, model, threads, refreshThreads, sidebarOpen, mobileNavOpen],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
