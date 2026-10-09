"use client";

import { ExternalLinkIcon, KeyRoundIcon, Loader2Icon, MenuIcon, PanelLeftIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app-provider";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { listKeys, removeKey, saveKey } from "@/lib/api";
import type { UserKey, UserKeys } from "@/lib/types";

const PROVIDERS: Record<string, { name: string; url: string }> = {
  openai: { name: "OpenAI", url: "https://platform.openai.com/api-keys" },
  anthropic: { name: "Anthropic (Claude)", url: "https://console.anthropic.com/settings/keys" },
  deepseek: { name: "DeepSeek", url: "https://platform.deepseek.com/api_keys" },
  google: { name: "Google Gemini", url: "https://aistudio.google.com/apikey" },
  groq: { name: "Groq", url: "https://console.groq.com/keys" },
  openrouter: { name: "OpenRouter", url: "https://openrouter.ai/settings/keys" },
};

export default function SettingsPage() {
  const { sidebarOpen, setSidebarOpen, setMobileNavOpen, account, refreshPlan } = useApp();
  const [data, setData] = useState<UserKeys | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listKeys()
      .then((keys) => {
        setData(keys);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(refresh, [refresh]);

  const changed = () => {
    refresh();
    refreshPlan();
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-1 px-2">
        <IconButton label="Open menu" className="md:hidden" onClick={() => setMobileNavOpen(true)}>
          <MenuIcon />
        </IconButton>
        {!sidebarOpen && (
          <IconButton label="Open sidebar" className="hidden md:inline-flex" onClick={() => setSidebarOpen(true)}>
            <PanelLeftIcon />
          </IconButton>
        )}
        <h1 className="px-2.5 text-base font-semibold">Settings</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-4 px-4 pt-4 pb-12">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-medium">
              <KeyRoundIcon className="size-4" /> Your API keys
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Add your own key to use that provider&apos;s models on your own account. Messages on your key don&apos;t
              count toward your daily limit. Keys are stored encrypted and never shown again, only their last four
              characters.
            </p>
          </div>

          {!account ? (
            <Notice>Sign-in is off on this server, so keys are set by its operator in .env.</Notice>
          ) : error ? (
            <Notice>
              {error}{" "}
              <button type="button" className="underline" onClick={refresh}>
                Retry
              </button>
            </Notice>
          ) : data === null ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-16 rounded-xl" />
              ))}
            </div>
          ) : !data.enabled ? (
            <Notice>This server doesn&apos;t accept personal API keys (USER_KEYS_SECRET isn&apos;t set).</Notice>
          ) : (
            <ul className="divide-y rounded-xl border">
              {data.providers.map((provider) => (
                <ProviderRow
                  key={provider}
                  provider={provider}
                  saved={data.keys.find((k) => k.provider === provider)}
                  onChange={changed}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border p-4 text-sm text-muted-foreground">{children}</p>;
}

function ProviderRow({ provider, saved, onChange }: { provider: string; saved?: UserKey; onChange: () => void }) {
  const meta = PROVIDERS[provider] ?? { name: provider, url: "" };
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!value.trim()) return;
    setBusy(true);
    try {
      const key = await saveKey(provider, value.trim());
      toast.success(
        key.verified
          ? `${meta.name} key saved`
          : `${meta.name} key saved, but ${meta.name} couldn't be reached to check it`,
      );
      setValue("");
      setEditing(false);
      onChange();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save the key");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await removeKey(provider);
      toast.success(`${meta.name} key removed`);
      onChange();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't remove the key");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{meta.name}</p>
        {saved && !editing ? (
          <p className="text-xs text-muted-foreground">
            <span className="font-mono">••••{saved.last4}</span> · added {new Date(saved.added_at).toLocaleDateString()}
            {!saved.verified && " · not verified"}
          </p>
        ) : (
          meta.url && (
            <a
              href={meta.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              Get a key <ExternalLinkIcon className="size-3" />
            </a>
          )
        )}
      </div>
      {saved && !editing ? (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setEditing(true)}>
            Replace
          </Button>
          <Button variant="outline" size="sm" disabled={busy} onClick={remove}>
            Remove
          </Button>
        </div>
      ) : (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Paste API key"
            aria-label={`${meta.name} API key`}
            className="h-8 w-full min-w-0 rounded-lg border bg-transparent px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50 sm:w-56"
          />
          <Button type="submit" size="sm" disabled={busy || !value.trim()}>
            {busy ? <Loader2Icon className="animate-spin" /> : "Save"}
          </Button>
          {saved && (
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </Button>
          )}
        </form>
      )}
    </li>
  );
}
