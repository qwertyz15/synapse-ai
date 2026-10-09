"use client";

import {
  EllipsisIcon,
  LibraryIcon,
  MonitorIcon,
  MoonIcon,
  PanelLeftIcon,
  PencilIcon,
  SearchIcon,
  SquarePenIcon,
  SunIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app-provider";
import { GithubSidebarItem } from "@/components/github-connect";
import { IconButton } from "@/components/icon-button";
import { SynapseLogo } from "@/components/logo";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { agentLabel } from "@/lib/agents";
import { deleteThread, renameThread } from "@/lib/api";
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
  const { threads, refreshThreads, setSidebarOpen, setMobileNavOpen } = useApp();
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<ThreadInfo | null>(null);
  const [deleting, setDeleting] = useState(false);

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const { agent_id, thread_id } = pendingDelete;
    setDeleting(true);
    try {
      const { attachments_removed } = await deleteThread(agent_id, thread_id);
      toast.success(
        attachments_removed
          ? `Chat deleted, with ${attachments_removed} attached file${attachments_removed === 1 ? "" : "s"}`
          : "Chat deleted",
      );
      if (pathname === `/chat/${agent_id}/${thread_id}`) router.push("/");
      refreshThreads();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't delete the chat");
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  };

  const rename = async (thread: ThreadInfo, title: string) => {
    try {
      await renameThread(thread.agent_id, thread.thread_id, title);
      refreshThreads();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't rename the chat");
    }
  };

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
          <SynapseLogo className="size-5 shrink-0" /> Synapse
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
        <NavLink href="/library" icon={<LibraryIcon />} active={pathname === "/library"} onClick={onNavigate}>
          Library
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
                {items.map((t) => (
                  <ThreadRow
                    key={`${t.agent_id}/${t.thread_id}`}
                    thread={t}
                    active={pathname === `/chat/${t.agent_id}/${t.thread_id}`}
                    onNavigate={onNavigate}
                    onRename={(title) => rename(t, title)}
                    onDelete={() => setPendingDelete(t)}
                  />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>

      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => !open && !deleting && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete chat?</AlertDialogTitle>
            <AlertDialogDescription>
              &ldquo;{pendingDelete?.title || "Untitled chat"}&rdquo; and any files attached to it will be permanently
              deleted. Files in your Library aren&apos;t affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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

function ThreadRow({
  thread,
  active,
  onNavigate,
  onRename,
  onDelete,
}: {
  thread: ThreadInfo;
  active: boolean;
  onNavigate?: () => void;
  onRename: (title: string) => Promise<void>;
  onDelete: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const startEditing = () => {
    setDraft(thread.title ?? "");
    setEditing(true);
  };

  const finishEditing = (save: boolean) => {
    if (!editing) return;
    setEditing(false);
    const title = draft.trim();
    if (save && title && title !== thread.title) onRename(title.slice(0, 200));
  };

  if (editing) {
    return (
      <li>
        <input
          autoFocus
          value={draft}
          maxLength={200}
          aria-label="Chat title"
          onChange={(e) => setDraft(e.target.value)}
          onFocus={(e) => e.target.select()}
          onBlur={() => finishEditing(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              finishEditing(true);
            } else if (e.key === "Escape") {
              e.preventDefault();
              finishEditing(false);
            }
          }}
          className="h-9 w-full rounded-lg bg-sidebar-accent px-2.5 text-sm ring-1 ring-ring outline-none"
        />
      </li>
    );
  }

  return (
    <li className="group/row relative">
      <Link
        href={`/chat/${thread.agent_id}/${thread.thread_id}`}
        onClick={onNavigate}
        title={thread.title ?? undefined}
        className={cn(
          "flex h-9 items-center rounded-lg pr-9 pl-2.5 text-sm hover:bg-sidebar-accent",
          (active || menuOpen) && "bg-sidebar-accent",
        )}
      >
        <span className="min-w-0 flex-1 truncate">{thread.title || "Untitled chat"}</span>
      </Link>
      <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
        <DropdownMenuTrigger
          aria-label={`Options for ${thread.title || "chat"}`}
          className={cn(
            "absolute top-1/2 right-1 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:text-foreground",
            menuOpen
              ? "opacity-100"
              : "opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100 max-md:opacity-100",
          )}
        >
          <EllipsisIcon className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-44">
          <DropdownMenuItem disabled className="text-xs">
            {agentLabel(thread.agent_id)}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={startEditing}>
            <PencilIcon /> Rename
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={onDelete}>
            <Trash2Icon /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}
