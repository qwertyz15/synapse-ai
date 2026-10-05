"use client";

import { ChevronUpIcon, ExternalLinkIcon, FolderGit2Icon, UnplugIcon } from "lucide-react";
import { usePathname } from "next/navigation";

import { useApp } from "@/components/app-provider";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuGroup,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { githubInstallUrl, githubLoginUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

export function GithubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" fill="currentColor" className={cn("size-4", className)}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

function useReturnTo() {
  return usePathname() || "/";
}

export function GithubSidebarItem() {
  const { github, disconnectGithub, githubWrite, setGithubWrite } = useApp();
  const returnTo = useReturnTo();
  if (!github?.configured) return null;

  if (!github.connected) {
    return (
      <a
        href={githubLoginUrl(returnTo)}
        className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-sm hover:bg-sidebar-accent"
      >
        <GithubMark />
        Connect GitHub
      </a>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-sm hover:bg-sidebar-accent">
        {github.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- tiny remote avatar; next/image would need remotePatterns
          <img src={github.avatar_url} alt="" className="size-5 rounded-full" />
        ) : (
          <GithubMark />
        )}
        <span className="min-w-0 flex-1 truncate text-left">@{github.login}</span>
        <ChevronUpIcon className="size-3.5 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Connected as @{github.login}</DropdownMenuLabel>
          <DropdownMenuItem render={<a href={githubInstallUrl(returnTo)} />}>
            <FolderGit2Icon /> Choose repositories
          </DropdownMenuItem>
          <DropdownMenuItem render={<a href={github.manage_url} target="_blank" rel="noreferrer" />}>
            <ExternalLinkIcon /> Manage on GitHub
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem checked={githubWrite} onCheckedChange={setGithubWrite}>
          <div className="flex flex-col">
            <span>Allow changes</span>
            <span className="text-xs text-muted-foreground">Create issues, PRs and edit files</span>
          </div>
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onClick={disconnectGithub}>
          <UnplugIcon /> Disconnect GitHub
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function GithubConnectCard({
  compact = false,
  mode = "connect",
}: {
  compact?: boolean;
  mode?: "connect" | "install";
}) {
  const returnTo = useReturnTo();
  const install = mode === "install";
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-2xl border text-center",
        compact ? "mt-3 px-4 py-4" : "px-6 py-8",
      )}
    >
      {install ? <FolderGit2Icon className="size-8" /> : <GithubMark className="size-8" />}
      <div>
        <p className="font-medium">{install ? "Choose repositories" : "Connect your GitHub account"}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {install
            ? "Pick which of your repositories the GitHub agent can work with."
            : "The GitHub agent works with your own repositories. You'll approve access on github.com."}
        </p>
      </div>
      <Button
        nativeButton={false}
        render={<a href={install ? githubInstallUrl(returnTo) : githubLoginUrl(returnTo)} />}
      >
        {install ? <FolderGit2Icon /> : <GithubMark />} {install ? "Choose repositories" : "Connect GitHub"}
      </Button>
    </div>
  );
}

export function GithubStatusBar() {
  const { github, disconnectGithub } = useApp();
  const returnTo = useReturnTo();
  if (!github?.connected) return null;
  return (
    <div className="mb-3 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <GithubMark className="size-3.5" /> Connected as <span className="text-foreground">@{github.login}</span>
      </span>
      <a href={githubInstallUrl(returnTo)} className="underline-offset-2 hover:text-foreground hover:underline">
        Choose repositories
      </a>
      <button
        type="button"
        onClick={disconnectGithub}
        className="underline-offset-2 hover:text-destructive hover:underline"
      >
        Disconnect
      </button>
    </div>
  );
}
