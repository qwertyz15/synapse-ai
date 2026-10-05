"use client";

import {
  FileTextIcon,
  LibraryIcon,
  Loader2Icon,
  PaperclipIcon,
  PlugIcon,
  PlusIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app-provider";
import { GithubMark } from "@/components/github-connect";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { supportsConnectors } from "@/lib/agents";
import { githubLoginUrl, uploadDocuments } from "@/lib/api";

import type { ChatAttachments } from "./use-chat-attachments";
import type { ChatConnectors } from "./use-chat-connectors";

const ACCEPT = ".pdf,.docx,.txt,.md";

export function AttachMenu({
  agent,
  chat,
  connectors: chatConnectors,
}: {
  agent: string;
  chat: ChatAttachments;
  connectors: ChatConnectors;
}) {
  const { github } = useApp();
  const { connectors, toggle: toggleConnector, enableAfterRedirect } = chatConnectors;
  const pathname = usePathname();
  const libraryInput = useRef<HTMLInputElement>(null);
  const chatInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const canConnect = supportsConnectors(agent) && !!github?.configured;
  const githubOn = connectors.includes("github");

  const upload = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    try {
      const result = await uploadDocuments(files);
      const indexed = result.new.length + result.updated.length + result.unchanged.length;
      const problems = { ...result.rejected, ...result.failed };
      if (indexed) toast.success(`Added ${indexed} document${indexed === 1 ? "" : "s"} to the library`);
      for (const [name, reason] of Object.entries(problems)) toast.error(`${name}: ${reason}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (libraryInput.current) libraryInput.current.value = "";
    }
  };

  const setGithub = (on: boolean) => {
    if (on && !github?.connected) {
      enableAfterRedirect("github");
      window.location.href = githubLoginUrl(pathname || "/");
      return;
    }
    toggleConnector("github", on);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="rounded-full text-muted-foreground"
              aria-label="Add files and connectors"
              disabled={uploading}
            />
          }
        >
          {uploading ? <Loader2Icon className="animate-spin" /> : <PlusIcon />}
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-64" side="top">
          <DropdownMenuItem onClick={() => chatInput.current?.click()}>
            <PaperclipIcon />
            <div className="flex flex-col">
              <span>Attach to this chat</span>
              <span className="text-xs text-muted-foreground">Only this conversation can use it</span>
            </div>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => libraryInput.current?.click()}>
            <LibraryIcon />
            <div className="flex flex-col">
              <span>Add to document library</span>
              <span className="text-xs text-muted-foreground">Searchable from every chat</span>
            </div>
          </DropdownMenuItem>
          {canConnect && (
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <PlugIcon /> Connectors
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="w-60">
                <DropdownMenuCheckboxItem checked={githubOn} onCheckedChange={setGithub}>
                  <GithubMark />
                  <span className="flex-1">GitHub</span>
                  <span className="text-xs text-muted-foreground">
                    {github?.connected ? `@${github.login}` : "Connect…"}
                  </span>
                </DropdownMenuCheckboxItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <input
        ref={libraryInput}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => upload(Array.from(e.target.files ?? []))}
      />
      <input
        ref={chatInput}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          chat.attach(files);
        }}
      />
    </>
  );
}

export function ConnectorChips({ agent, connectors: chatConnectors }: { agent: string; connectors: ChatConnectors }) {
  const { github, githubWrite } = useApp();
  const { connectors, toggle: toggleConnector } = chatConnectors;
  if (!supportsConnectors(agent) || !github?.configured || !connectors.includes("github")) return null;
  return (
    <span className="inline-flex h-7 items-center gap-1.5 rounded-full border bg-muted/50 pr-1 pl-2.5 text-xs">
      <GithubMark className="size-3.5" />
      GitHub
      {github.connected && githubWrite && <span className="text-amber-600 dark:text-amber-400">· can edit</span>}
      {!github.connected && <span className="text-muted-foreground">· not connected</span>}
      <button
        type="button"
        onClick={() => toggleConnector("github", false)}
        aria-label="Turn off GitHub"
        className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <XIcon className="size-3" />
      </button>
    </span>
  );
}

export function AttachmentChips({ chat }: { chat: ChatAttachments }) {
  if (!chat.unsent.length && !chat.pending.length) return null;
  return (
    <div className="flex flex-wrap gap-2 px-4 pt-3">
      {chat.unsent.map((a) => (
        <span
          key={a.name}
          title={`${a.name} · will be sent with your next message`}
          className="inline-flex max-w-64 items-center gap-2 rounded-xl border bg-muted/40 py-1.5 pr-1.5 pl-2.5 text-xs"
        >
          <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{a.name}</span>
          <button
            type="button"
            onClick={() => chat.detach(a.name)}
            aria-label={`Remove ${a.name}`}
            className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <XIcon className="size-3" />
          </button>
        </span>
      ))}
      {chat.pending.map((name) => (
        <span
          key={`pending-${name}`}
          className="inline-flex max-w-64 items-center gap-2 rounded-xl border border-dashed py-1.5 pr-2.5 pl-2.5 text-xs text-muted-foreground"
        >
          <Loader2Icon className="size-4 shrink-0 animate-spin" />
          <span className="truncate">{name}</span>
        </span>
      ))}
    </div>
  );
}

/** Files already sent in this chat; they stay searchable, so this is where to review or remove them. */
export function ChatFilesButton({ chat }: { chat: ChatAttachments }) {
  const sent = chat.attachments.filter((a) => !chat.unsent.includes(a));
  if (!sent.length) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="rounded-full text-muted-foreground"
            aria-label={`${sent.length} file${sent.length === 1 ? "" : "s"} in this chat`}
          />
        }
      >
        <PaperclipIcon /> {sent.length}
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-72">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Files in this chat · always searchable here</DropdownMenuLabel>
          {sent.map((a) => (
            <DropdownMenuItem key={a.name} onClick={() => chat.detach(a.name)} className="group/file">
              <FileTextIcon />
              <span className="min-w-0 flex-1 truncate">{a.name}</span>
              <Trash2Icon className="opacity-60 group-hover/file:text-destructive group-hover/file:opacity-100" />
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
