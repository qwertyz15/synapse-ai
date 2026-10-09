"use client";

import { MenuIcon, PanelLeftIcon, SearchIcon, ShieldIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app-provider";
import { IconButton } from "@/components/icon-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, listUsers, updateUser } from "@/lib/api";
import type { AdminUser, AdminUserUpdate } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function AdminPage() {
  const { sidebarOpen, setSidebarOpen, setMobileNavOpen } = useApp();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const refresh = useCallback(() => {
    listUsers()
      .then((u) => {
        setUsers(u);
        setError(null);
      })
      .catch((err: Error) => setError(err instanceof ApiError && err.status === 403 ? "Admins only." : err.message));
  }, []);

  useEffect(refresh, [refresh]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (users ?? []).filter((u) => !q || u.email.toLowerCase().includes(q) || u.name?.toLowerCase().includes(q));
  }, [users, query]);

  const change = async (user: AdminUser, update: AdminUserUpdate) => {
    try {
      const updated = await updateUser(user.id, update);
      setUsers((all) => all?.map((u) => (u.id === updated.id ? updated : u)) ?? null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't update the account");
    }
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
        <h1 className="flex items-center gap-2 px-2.5 text-base font-semibold">
          <ShieldIcon className="size-4" /> Admin
        </h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl space-y-4 px-4 pt-4 pb-12">
          {error ? (
            <p className="rounded-xl border p-4 text-sm text-muted-foreground">{error}</p>
          ) : users === null ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-14 rounded-xl" />
              ))}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">
                  {users.length} account{users.length === 1 ? "" : "s"} · changes apply right away
                </p>
                <label className="flex h-9 w-full items-center gap-2 rounded-lg border px-2.5 sm:w-64">
                  <SearchIcon className="size-4 text-muted-foreground" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search by name or email"
                    aria-label="Search accounts"
                    className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                  />
                </label>
              </div>
              <div className="overflow-x-auto rounded-xl border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Account</TableHead>
                      <TableHead>Plan</TableHead>
                      <TableHead>Today</TableHead>
                      <TableHead>Daily limit</TableHead>
                      <TableHead>Own keys</TableHead>
                      <TableHead>Last active</TableHead>
                      <TableHead className="text-right">Access</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {shown.map((u) => (
                      <UserRow key={u.id} user={u} onChange={(update) => change(u, update)} />
                    ))}
                  </TableBody>
                </Table>
              </div>
              {shown.length === 0 && <p className="text-center text-sm text-muted-foreground">No accounts match.</p>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function UserRow({ user, onChange }: { user: AdminUser; onChange: (update: AdminUserUpdate) => void }) {
  const isAdmin = user.plan === "admin";
  return (
    <TableRow className={cn(user.blocked && "opacity-60")}>
      <TableCell>
        <div className="flex min-w-48 items-center gap-2.5">
          {user.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- tiny remote avatar; next/image would need remotePatterns
            <img src={user.avatar_url} alt="" referrerPolicy="no-referrer" className="size-7 rounded-full" />
          ) : (
            <span className="flex size-7 items-center justify-center rounded-full bg-muted text-xs font-medium uppercase">
              {(user.name || user.email).charAt(0)}
            </span>
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{user.name || user.email}</p>
            <p className="truncate text-xs text-muted-foreground">{user.email}</p>
          </div>
        </div>
      </TableCell>
      <TableCell>
        {isAdmin ? (
          <Badge variant="secondary">Admin</Badge>
        ) : (
          <select
            value={user.plan}
            onChange={(e) => onChange({ plan: e.target.value as "free" | "unlimited" })}
            aria-label={`Plan for ${user.email}`}
            className="h-8 rounded-lg border bg-background px-2 text-sm"
          >
            <option value="free">Free</option>
            <option value="unlimited">Unlimited</option>
          </select>
        )}
      </TableCell>
      <TableCell className="text-sm tabular-nums">
        {user.messages_today}
        <span className="text-muted-foreground"> / {user.effective_limit ?? "∞"}</span>
      </TableCell>
      <TableCell>
        <LimitInput key={user.daily_message_limit ?? "default"} user={user} onChange={onChange} />
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {user.own_key_providers.length ? (
            user.own_key_providers.map((p) => (
              <Badge key={p} variant="outline">
                {p}
              </Badge>
            ))
          ) : (
            <span className="text-xs text-muted-foreground">None</span>
          )}
        </div>
      </TableCell>
      <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
        {new Date(user.last_login_at).toLocaleDateString()}
      </TableCell>
      <TableCell className="text-right">
        {isAdmin ? (
          <span className="text-xs text-muted-foreground">—</span>
        ) : (
          <Button
            size="sm"
            variant={user.blocked ? "outline" : "ghost"}
            className={cn(!user.blocked && "text-destructive hover:text-destructive")}
            onClick={() => onChange({ blocked: !user.blocked })}
          >
            {user.blocked ? "Unblock" : "Block"}
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

/** Saves on Enter or blur; empty means the plan's default. Remounted (by key) when the saved limit changes. */
function LimitInput({ user, onChange }: { user: AdminUser; onChange: (update: AdminUserUpdate) => void }) {
  const current = user.daily_message_limit?.toString() ?? "";
  const [value, setValue] = useState(current);

  const commit = () => {
    const trimmed = value.trim();
    if (trimmed === current) return;
    const limit = trimmed === "" ? null : Number(trimmed);
    if (limit !== null && (!Number.isInteger(limit) || limit < 0)) {
      setValue(current);
      toast.error("The daily limit must be a whole number, or empty for the plan's default.");
      return;
    }
    onChange({ daily_message_limit: limit });
  };

  return (
    <input
      inputMode="numeric"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      placeholder="Plan default"
      aria-label={`Daily limit for ${user.email}`}
      className="h-8 w-28 rounded-lg border bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
    />
  );
}
