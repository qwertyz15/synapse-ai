"use client";

import {
  AlertCircleIcon,
  CheckIcon,
  CopyIcon,
  FileTextIcon,
  RotateCcwIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react";
import { memo, useState } from "react";
import { toast } from "sonner";

import { GithubConnectCard } from "@/components/github-connect";
import { IconButton } from "@/components/icon-button";
import { Button } from "@/components/ui/button";
import { sendFeedback } from "@/lib/api";
import { turnText, type AssistantTurn, type UserTurn } from "@/lib/chat-reducer";
import { cn } from "@/lib/utils";

import { Blocks } from "./blocks";

export const UserMessage = memo(function UserMessage({ turn }: { turn: UserTurn }) {
  return (
    <div className="flex flex-col items-end gap-1.5">
      {turn.attachments?.map((name) => (
        <span
          key={name}
          className="inline-flex max-w-[85%] items-center gap-2 rounded-xl border px-3 py-2 text-sm sm:max-w-[70%]"
        >
          <FileTextIcon className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{name}</span>
        </span>
      ))}
      <div className="max-w-[85%] rounded-3xl bg-muted px-4 py-2.5 whitespace-pre-wrap sm:max-w-[70%]">{turn.text}</div>
    </div>
  );
});

export const AssistantMessage = memo(function AssistantMessage({
  turn,
  isLast,
  onRetry,
}: {
  turn: AssistantTurn;
  isLast: boolean;
  onRetry?: () => void;
}) {
  const streaming = turn.status === "streaming";
  const empty = turn.blocks.length === 0;

  return (
    <div className="group/turn">
      {empty && streaming ? <ThinkingDots /> : <Blocks blocks={turn.blocks} streaming={streaming} />}

      {turn.status === "error" && turn.errorCode === "github_not_connected" ? (
        <GithubConnectCard compact />
      ) : (
        turn.status === "error" && (
          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <AlertCircleIcon className="size-4 shrink-0" />
            <span className="min-w-0 flex-1">{friendlyError(turn.error)}</span>
            {isLast && onRetry && (
              <Button size="sm" variant="outline" onClick={onRetry}>
                <RotateCcwIcon /> Retry
              </Button>
            )}
          </div>
        )
      )}
      {turn.status === "stopped" && <p className="mt-2 text-xs text-muted-foreground">Stopped</p>}
      {empty && turn.status === "done" && <p className="text-sm text-muted-foreground">No response.</p>}

      {!streaming && !empty && <Actions turn={turn} visible={isLast} />}
    </div>
  );
});

function friendlyError(error?: string) {
  if (!error || error === "Internal server error" || error === "Unexpected error") {
    return "Something went wrong while generating this response.";
  }
  return error;
}

function ThinkingDots() {
  return (
    <div className="flex h-7 items-center gap-1" aria-label="Thinking">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-2 animate-bounce rounded-full bg-muted-foreground/60"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  );
}

function Actions({ turn, visible }: { turn: AssistantTurn; visible: boolean }) {
  const [copied, setCopied] = useState(false);
  const [vote, setVote] = useState<1 | 0 | null>(null);

  const copy = async () => {
    await navigator.clipboard.writeText(turnText(turn));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const rate = async (score: 1 | 0) => {
    if (!turn.runId || vote === score) return;
    setVote(score);
    try {
      await sendFeedback(turn.runId, score);
      toast.success("Thanks for your feedback");
    } catch {
      setVote(null);
      toast.error("Couldn't save feedback. The service needs LangSmith configured to record it.");
    }
  };

  return (
    <div
      className={cn(
        "mt-2 -ml-2 flex items-center gap-0.5 text-muted-foreground transition-opacity",
        visible ? "opacity-100" : "opacity-0 group-hover/turn:opacity-100 focus-within:opacity-100",
      )}
    >
      <IconButton label={copied ? "Copied" : "Copy"} size="icon-sm" onClick={copy}>
        {copied ? <CheckIcon /> : <CopyIcon />}
      </IconButton>
      {turn.runId && (
        <>
          <IconButton label="Good response" size="icon-sm" onClick={() => rate(1)}>
            <ThumbsUpIcon className={cn(vote === 1 && "fill-current")} />
          </IconButton>
          <IconButton label="Bad response" size="icon-sm" onClick={() => rate(0)}>
            <ThumbsDownIcon className={cn(vote === 0 && "fill-current")} />
          </IconButton>
        </>
      )}
    </div>
  );
}
