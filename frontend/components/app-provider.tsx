"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { isVisibleAgent, type Connector } from "@/lib/agents";
import { disconnectGithub, getAllThreads, getGithubStatus, getInfo, type GithubStatus } from "@/lib/api";
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
  github: GithubStatus | null;
  disconnectGithub: () => Promise<void>;
  connectors: Connector[];
  toggleConnector: (connector: Connector, on: boolean) => void;
  githubWrite: boolean;
  setGithubWrite: (on: boolean) => void;
};

const GITHUB_ERRORS: Record<string, string> = {
  access_denied: "GitHub access wasn't granted.",
  not_configured: "GitHub isn't set up on this server (missing GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET).",
  invalid_state: "The GitHub sign-in expired or was opened in another browser. Please try again.",
};

const AppContext = createContext<AppState | null>(null);

const STORAGE_AGENT = "ui.agent";
const STORAGE_MODEL = "ui.model";
const STORAGE_SIDEBAR = "ui.sidebar";
const STORAGE_CONNECTORS = "ui.connectors";
const STORAGE_GITHUB_WRITE = "ui.githubWrite";

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
  const [github, setGithub] = useState<GithubStatus | null>(null);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [githubWrite, setGithubWriteState] = useState(false);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- restoring per-browser preferences after hydration */
    setConnectors(load(STORAGE_CONNECTORS) === "github" ? ["github"] : []);
    setGithubWriteState(load(STORAGE_GITHUB_WRITE) === "true");
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const toggleConnector = useCallback((connector: Connector, on: boolean) => {
    setConnectors((current) => {
      const next = on ? [...new Set([...current, connector])] : current.filter((c) => c !== connector);
      save(STORAGE_CONNECTORS, next.join(","));
      return next;
    });
  }, []);

  const setGithubWrite = useCallback((on: boolean) => {
    setGithubWriteState(on);
    save(STORAGE_GITHUB_WRITE, String(on));
  }, []);

  useEffect(() => {
    getGithubStatus()
      .then(setGithub)
      .catch(() => setGithub({ configured: false, connected: false, login: null, avatar_url: null }));

    const url = new URL(window.location.href);
    const result = url.searchParams.get("github");
    if (!result) return;
    if (result === "connected") toast.success("GitHub connected");
    else
      toast.error(GITHUB_ERRORS[url.searchParams.get("reason") ?? ""] ?? "Couldn't connect GitHub. Please try again.");
    url.searchParams.delete("github");
    url.searchParams.delete("reason");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }, []);

  const disconnect = useCallback(async () => {
    try {
      await disconnectGithub();
      toggleConnector("github", false);
      setGithub((g) => (g ? { ...g, connected: false, login: null, avatar_url: null, installed: null } : g));
      toast.success("GitHub disconnected", {
        description: "The app may still be installed on your repositories.",
        action: {
          label: "Manage on GitHub",
          onClick: () => window.open("https://github.com/settings/installations", "_blank", "noopener"),
        },
      });
    } catch {
      toast.error("Couldn't disconnect GitHub");
    }
  }, [toggleConnector]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- restoring a per-browser preference after hydration
    setSidebarOpenState(load(STORAGE_SIDEBAR) !== "closed");
  }, []);

  useEffect(() => {
    let cancelled = false;
    getInfo()
      .then((serviceMeta) => {
        if (cancelled) return;
        const meta = { ...serviceMeta, agents: serviceMeta.agents.filter((a) => isVisibleAgent(a.key)) };
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
      github,
      disconnectGithub: disconnect,
      connectors,
      toggleConnector,
      githubWrite,
      setGithubWrite,
    }),
    [
      info,
      infoError,
      agent,
      model,
      threads,
      refreshThreads,
      sidebarOpen,
      mobileNavOpen,
      github,
      disconnect,
      connectors,
      toggleConnector,
      githubWrite,
      setGithubWrite,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
