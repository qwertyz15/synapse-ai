"use client";

import { FileTextIcon, MonitorIcon, MoonIcon, PanelLeftIcon, SearchIcon, SquarePenIcon, SunIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useMemo, useState } from "react";

import { useApp } from "@/components/app-provider";
import { GithubSidebarItem } from "@/components/github-connect";
import { IconButton } from "@/components/icon-button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { agentLabel } from "@/lib/agents";
import type { ThreadInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

const GROUPS = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"] as const;

function groupOf(updatedAt: string | null, now: Date): (typeof GROUPS)[number] {
  if (!updatedAt) return "Older";
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const t = new Date(updatedAt).getTime();
  const day = 86_400_000;
  if (t >= startOfToday) return "Today";
  if (t >= startOfToday - day) return "Yesterday";
  if (t >= startOfToday - 7 * day) return "Previous 7 days";
  if (t >= startOfToday - 30 * day) return "Previous 30 days";
  return "Older";
}

export function AppSidebar() {
  const { sidebarOpen, mobileNavOpen, setMobileNavOpen } = useApp();
  return (
    <>
      <aside
        className={cn(
          "hidden shrink-0 overflow-hidden bg-sidebar text-sidebar-foreground transition-[width] duration-200 md:block",
          sidebarOpen ? "w-[260px] border-r border-sidebar-border" : "w-0",
        )}
      >
        <div className="h-full w-[260px]">
          <SidebarBody />
        </div>
      </aside>
      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" showCloseButton={false} className="w-[280px] gap-0 bg-sidebar p-0 md:hidden">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SidebarBody onNavigate={() => setMobileNavOpen(false)} />
        </SheetContent>
      </Sheet>
    </>
  );
}

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const { threads, setSidebarOpen, setMobileNavOpen } = useApp();
  const pathname = usePathname();
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    if (!threads) return null;
    const now = new Date();
    const q = query.trim().toLowerCase();
    const map = new Map<string, ThreadInfo[]>();
    for (const t of threads) {
      if (q && !(t.title ?? "").toLowerCase().includes(q)) continue;
      const g = groupOf(t.updated_at, now);
      map.set(g, [...(map.get(g) ?? []), t]);
    }
    return GROUPS.filter((g) => map.has(g)).map((g) => [g, map.get(g)!] as const);
  }, [threads, query]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-2 pt-2">
        <Link href="/" onClick={onNavigate} className="flex items-center gap-2 px-2 text-sm font-semibold">
          <span className="text-lg">🧠</span> Agent Toolkit
        </Link>
        <IconButton
          label="Close sidebar"
          side="right"
          onClick={() => (onNavigate ? setMobileNavOpen(false) : setSidebarOpen(false))}
        >
          <PanelLeftIcon />
        </IconButton>
      </div>

      <nav className="flex flex-col gap-0.5 px-2 py-2">
        <NavLink href="/" icon={<SquarePenIcon />} active={pathname === "/"} onClick={onNavigate}>
          New chat
        </NavLink>
        <NavLink href="/documents" icon={<FileTextIcon />} active={pathname === "/documents"} onClick={onNavigate}>
          Documents
        </NavLink>
        <label className="mt-1 flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm text-muted-foreground focus-within:bg-sidebar-accent">
          <SearchIcon className="size-4 shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="w-full bg-transparent text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {grouped === null ? (
          <div className="space-y-2 px-2 pt-4">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-5" style={{ width: `${55 + ((i * 17) % 40)}%` }} />
            ))}
          </div>
        ) : grouped.length === 0 ? (
          <p className="px-2.5 pt-4 text-sm text-muted-foreground">
            {query ? "No chats match your search." : "Your conversations will appear here."}
          </p>
        ) : (
          grouped.map(([group, items]) => (
            <section key={group} className="pt-4">
              <h3 className="px-2.5 pb-1 text-xs font-medium text-muted-foreground">{group}</h3>
              <ul>
                {items.map((t) => {
                  const href = `/chat/${t.agent_id}/${t.thread_id}`;
                  return (
                    <li key={`${t.agent_id}/${t.thread_id}`}>
                      <Link
                        href={href}
                        onClick={onNavigate}
                        title={t.title ?? undefined}
                        className={cn(
                          "group flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm hover:bg-sidebar-accent",
                          pathname === href && "bg-sidebar-accent",
                        )}
                      >
                        <span className="min-w-0 flex-1 truncate">{t.title || "Untitled chat"}</span>
                        <span className="hidden shrink-0 text-[10px] text-muted-foreground group-hover:inline">
                          {agentLabel(t.agent_id)}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>

      <div className="border-t border-sidebar-border p-2">
        <GithubSidebarItem />
        <ThemeMenu />
      </div>
    </div>
  );
}

function NavLink({
  href,
  icon,
  active,
  onClick,
  children,
}: {
  href: string;
  icon: React.ReactNode;
  active: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm hover:bg-sidebar-accent [&_svg]:size-4",
        active && "bg-sidebar-accent",
      )}
    >
      {icon}
      {children}
    </Link>
  );
}

function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-sm hover:bg-sidebar-accent">
        <SunIcon className="size-4 dark:hidden" />
        <MoonIcon className="hidden size-4 dark:block" />
        Theme
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-48">
        <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={(v) => setTheme(v as string)}>
          <DropdownMenuRadioItem value="light">
            <SunIcon /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <MoonIcon /> Dark
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <MonitorIcon /> System
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
