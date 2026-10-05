"use client";

import { ArrowDownIcon } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";

import { useApp } from "@/components/app-provider";
import { GithubConnectCard, GithubStatusBar } from "@/components/github-connect";
import { Button } from "@/components/ui/button";
import { suggestionsFor } from "@/lib/agents";
import { GITHUB_AGENT } from "@/lib/constants";
import { ApiError, streamChat } from "@/lib/api";
import { chatReducer, type Turn } from "@/lib/chat-reducer";

import { ChatHeader } from "./chat-header";
import { Composer, type ComposerHandle } from "./composer";
import { AssistantMessage, UserMessage } from "./message";

type Props = {
  agent: string;
  threadId: string;
  initialTurns?: Turn[];
  isNew?: boolean;
};

export function ChatView({ agent, threadId, initialTurns = [], isNew = false }: Props) {
  const { info, model, refreshThreads, github } = useApp();
  const [turns, dispatch] = useReducer(chatReducer, initialTurns);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const composerRef = useRef<ComposerHandle>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const urlSetRef = useRef(!isNew);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    async (text: string) => {
      if (abortRef.current) return;
      dispatch({ type: "user", text });
      stickRef.current = true;
      if (!urlSetRef.current) {
        urlSetRef.current = true;
        window.history.replaceState(null, "", `/chat/${agent}/${threadId}`);
      }
      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);
      try {
        for await (const event of streamChat(
          agent,
          { message: text, thread_id: threadId, model: model || undefined },
          controller.signal,
        )) {
          dispatch({ type: "event", event });
        }
        dispatch({ type: "event", event: { type: "done" } });
      } catch (err) {
        if (controller.signal.aborted) dispatch({ type: "stopped" });
        else
          dispatch({
            type: "failed",
            error: err instanceof Error ? err.message : String(err),
            code: err instanceof ApiError ? err.code : undefined,
          });
      } finally {
        abortRef.current = null;
        setStreaming(false);
        refreshThreads();
        composerRef.current?.focus();
      }
    },
    [agent, threadId, model, refreshThreads],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const retry = useCallback(() => {
    const lastUser = [...turns].reverse().find((t) => t.role === "user");
    if (lastUser?.role === "user") send(lastUser.text);
  }, [turns, send]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickRef.current = atBottom;
    setShowJump(!atBottom);
  };

  const jumpToBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const description = info?.agents.find((a) => a.key === agent)?.description;
  const empty = turns.length === 0;
  const isGithubAgent = agent === GITHUB_AGENT && !!github?.configured;
  const needsGithub = isGithubAgent && !github?.connected;
  const needsInstall = isGithubAgent && !!github?.connected && github.installed === false;

  const composer = (
    <Composer
      ref={composerRef}
      onSend={send}
      onStop={stop}
      streaming={streaming}
      disabled={!info || needsGithub}
      placeholder={needsGithub ? "Connect GitHub to chat with this agent" : empty ? "Ask anything" : "Reply…"}
    />
  );

  return (
    <div className="flex h-full flex-col">
      <ChatHeader agent={agent} hasMessages={!empty} />

      {empty ? (
        <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[10vh]">
          <div className="w-full max-w-3xl">
            <h1 className="mb-2 text-center text-3xl font-semibold tracking-tight">What can I help with?</h1>
            {description && <p className="mb-8 text-center text-sm text-muted-foreground">{description}</p>}
            {isGithubAgent && <GithubStatusBar />}
            {needsGithub ? <GithubConnectCard /> : needsInstall ? <GithubConnectCard mode="install" /> : composer}
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {(agent && !needsGithub && !needsInstall ? suggestionsFor(agent) : []).map((s) => (
                <button
                  key={s}
                  type="button"
                  disabled={!info}
                  onClick={() => send(s)}
                  className="rounded-2xl border px-4 py-3 text-left text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 pt-6 pb-10">
              {turns.map((turn, i) =>
                turn.role === "user" ? (
                  <UserMessage key={turn.id} turn={turn} />
                ) : (
                  <AssistantMessage
                    key={turn.id}
                    turn={turn}
                    isLast={i === turns.length - 1}
                    onRetry={streaming ? undefined : retry}
                  />
                ),
              )}
            </div>
          </div>
          <div className="relative mx-auto w-full max-w-3xl px-4 pb-3">
            {showJump && (
              <Button
                variant="outline"
                size="icon"
                onClick={jumpToBottom}
                aria-label="Scroll to bottom"
                className="absolute -top-12 left-1/2 -translate-x-1/2 rounded-full bg-background shadow-md"
              >
                <ArrowDownIcon />
              </Button>
            )}
            {composer}
            <p className="pt-2 text-center text-xs text-muted-foreground">
              AI can make mistakes. Check important info.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
