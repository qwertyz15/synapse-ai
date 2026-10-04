"use client";

import { CheckIcon, ChevronDownIcon, MenuIcon, PanelLeftIcon, SquarePenIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useApp } from "@/components/app-provider";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { agentLabel } from "@/lib/agents";

export function ChatHeader({ agent, hasMessages }: { agent: string; hasMessages: boolean }) {
  const { info, setAgent, sidebarOpen, setSidebarOpen, setMobileNavOpen } = useApp();
  const router = useRouter();

  const choose = (key: string) => {
    setAgent(key);
    // A thread belongs to one agent's graph, so switching agents starts a new chat.
    if (hasMessages || key !== agent) router.push("/");
  };

  return (
    <header className="flex h-14 shrink-0 items-center gap-1 px-2">
      <IconButton label="Open menu" className="md:hidden" onClick={() => setMobileNavOpen(true)}>
        <MenuIcon />
      </IconButton>
      {!sidebarOpen && (
        <IconButton label="Open sidebar" className="hidden md:inline-flex" onClick={() => setSidebarOpen(true)}>
          <PanelLeftIcon />
        </IconButton>
      )}

      <DropdownMenu>
        <DropdownMenuTrigger
          disabled={!info}
          render={<Button variant="ghost" className="h-9 gap-1 px-2.5 text-base font-semibold" />}
        >
          {agent ? agentLabel(agent) : "Loading…"}
          <ChevronDownIcon className="text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="max-h-[70vh] w-80">
          {info?.agents.map((a) => (
            <DropdownMenuItem key={a.key} onClick={() => choose(a.key)} className="items-start gap-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{agentLabel(a.key)}</div>
                <div className="line-clamp-2 text-xs text-muted-foreground">{a.description}</div>
              </div>
              {a.key === agent && <CheckIcon className="mt-0.5 size-4" />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <div className="ml-auto">
        <IconButton label="New chat" render={<Link href="/" />} nativeButton={false}>
          <SquarePenIcon />
        </IconButton>
      </div>
    </header>
  );
}
