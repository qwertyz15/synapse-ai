"use client";

import { MessageSquareOffIcon } from "lucide-react";
import Link from "next/link";
import { use, useEffect, useState } from "react";

import { useApp } from "@/components/app-provider";
import { ChatHeader } from "@/components/chat/chat-header";
import { ChatView } from "@/components/chat/chat-view";
import { ServiceError } from "@/components/service-error";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getHistory } from "@/lib/api";
import { historyToTurns, type Turn } from "@/lib/chat-reducer";

type Loaded = { key: string } & ({ status: "ready"; turns: Turn[] } | { status: "error"; message: string });

export default function ChatThreadPage({ params }: PageProps<"/chat/[agent]/[threadId]">) {
  const { agent, threadId } = use(params);
  const { info, infoError, setAgent, showChatModel } = useApp();
  const key = `${agent}/${threadId}`;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const state = loaded?.key === key ? loaded : ({ status: "loading" } as const);
  const known = !info || info.agents.some((a) => a.key === agent);

  useEffect(() => {
    if (info && known) setAgent(agent);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync once per opened chat
  }, [info, agent, known]);

  useEffect(() => {
    let cancelled = false;
    getHistory(agent, threadId)
      .then((history) => {
        if (cancelled) return;
        setLoaded({ key, status: "ready", turns: historyToTurns(history.messages) });
        showChatModel(history.model);
      })
      .catch((err: Error) => !cancelled && setLoaded({ key, status: "error", message: err.message }));
    return () => {
      cancelled = true;
    };
  }, [agent, threadId, key, showChatModel]);

  if (infoError) return <ServiceError message={infoError} />;

  if (!known || state.status === "error") {
    return (
      <div className="flex h-full flex-col">
        <ChatHeader agent={known ? agent : ""} hasMessages />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <MessageSquareOffIcon className="size-10 text-muted-foreground" />
          <h1 className="text-lg font-semibold">This chat couldn&apos;t be opened</h1>
          <p className="max-w-md text-sm text-muted-foreground">
            {!known ? `There's no agent called "${agent}".` : state.status === "error" ? state.message : ""}
          </p>
          <Button variant="outline" nativeButton={false} render={<Link href="/" />}>
            Start a new chat
          </Button>
        </div>
      </div>
    );
  }

  if (state.status === "loading") {
    return (
      <div className="flex h-full flex-col">
        <ChatHeader agent={agent} hasMessages />
        <div className="mx-auto w-full max-w-3xl space-y-8 px-4 pt-6">
          <Skeleton className="ml-auto h-10 w-1/2 rounded-3xl" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>
      </div>
    );
  }

  return <ChatView key={key} agent={agent} threadId={threadId} initialTurns={state.turns} />;
}
