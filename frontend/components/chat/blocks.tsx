"use client";

import {
  BotIcon,
  CalculatorIcon,
  CheckIcon,
  ChevronRightIcon,
  CircleDotIcon,
  CloudSunIcon,
  FileCodeIcon,
  FileSearchIcon,
  FolderGit2Icon,
  GitBranchIcon,
  GitCommitHorizontalIcon,
  GitPullRequestIcon,
  GlobeIcon,
  ListChecksIcon,
  Loader2Icon,
  SearchCodeIcon,
  UserIcon,
  WrenchIcon,
  XIcon,
} from "lucide-react";
import { useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Block, SubAgentBlock, TaskBlock, ToolBlock } from "@/lib/chat-reducer";
import { summarizeWork, toolLabel } from "@/lib/steps";
import { cn } from "@/lib/utils";

import { Markdown } from "./markdown";

const ICONS: Record<string, React.ElementType> = {
  DocumentSearch: FileSearchIcon,
  WebSearch: GlobeIcon,
  Calculator: CalculatorIcon,
  Weather: CloudSunIcon,
  search_repositories: FolderGit2Icon,
  search_code: SearchCodeIcon,
  get_file_contents: FileCodeIcon,
  list_commits: GitCommitHorizontalIcon,
  get_commit: GitCommitHorizontalIcon,
  list_branches: GitBranchIcon,
  list_issues: CircleDotIcon,
  search_issues: CircleDotIcon,
  issue_read: CircleDotIcon,
  get_issue: CircleDotIcon,
  create_issue: CircleDotIcon,
  list_pull_requests: GitPullRequestIcon,
  search_pull_requests: GitPullRequestIcon,
  pull_request_read: GitPullRequestIcon,
  get_pull_request: GitPullRequestIcon,
  create_pull_request: GitPullRequestIcon,
  get_me: UserIcon,
};

const humanize = (name: string) => {
  const s = name.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

export function Blocks({ blocks, streaming, muted = false }: { blocks: Block[]; streaming: boolean; muted?: boolean }) {
  return (
    <div className={cn("flex flex-col", muted ? "gap-1.5" : "gap-3")}>
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "text":
            return muted ? (
              <div key={i} className="text-sm text-muted-foreground">
                <Markdown text={b.text} />
              </div>
            ) : (
              <Markdown key={i} text={b.text} />
            );
          case "tool":
            return <ToolStep key={b.id} tool={b} />;
          case "task":
            return <TaskCard key={b.task.run_id} block={b} />;
          case "subagent":
            return <SubAgent key={b.id} block={b} streaming={streaming} />;
        }
      })}
    </div>
  );
}

function StatusIcon({ status }: { status: "pending" | "success" | "error" }) {
  if (status === "pending") return <Loader2Icon className="size-3.5 animate-spin text-muted-foreground" />;
  // Muted on purpose: the assistant usually recovers from a failed step, so red reads as alarming.
  if (status === "error") return <XIcon className="size-3.5 text-muted-foreground/70" />;
  return <CheckIcon className="size-3.5 text-emerald-600 dark:text-emerald-400" />;
}

function formatValue(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

/**
 * Everything the assistant did before answering, collapsed into one line (like ChatGPT's
 * "Thought for…"). While it works the line shows the current step; click to see every step.
 */
export function Work({ blocks, streaming }: { blocks: Block[]; streaming: boolean }) {
  const [open, setOpen] = useState(false);
  const summary = summarizeWork(blocks, streaming);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mb-2 text-sm">
      <CollapsibleTrigger className="flex w-full max-w-full items-center gap-2 rounded-lg py-1 text-left text-muted-foreground hover:text-foreground">
        {summary.active ? (
          <Loader2Icon className="size-4 shrink-0 animate-spin" />
        ) : (
          <ListChecksIcon className="size-4 shrink-0" />
        )}
        <span className={cn("min-w-0 truncate", summary.active && "animate-pulse")}>{summary.headline}</span>
        {summary.steps > 1 && <span className="ml-auto shrink-0 text-xs opacity-70">{summary.steps} steps</span>}
        <ChevronRightIcon
          className={cn("size-3.5 shrink-0 transition-transform", summary.steps <= 1 && "ml-auto", open && "rotate-90")}
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1 mb-4 ml-2 border-l-2 pl-4">
          <Blocks blocks={blocks} streaming={streaming} muted />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ToolStep({ tool }: { tool: ToolBlock }) {
  const [open, setOpen] = useState(false);
  const Icon = ICONS[tool.name] ?? WrenchIcon;
  const { label, detail: summary } = toolLabel(tool);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="text-sm">
      <CollapsibleTrigger className="group flex max-w-full items-center gap-2 rounded-lg py-1 text-muted-foreground hover:text-foreground">
        <Icon className="size-4 shrink-0" />
        <span className={cn("shrink-0", tool.status === "pending" && "animate-pulse")}>{label}</span>
        {summary && <span className="min-w-0 truncate opacity-80">“{summary}”</span>}
        <StatusIcon status={tool.status} />
        <ChevronRightIcon className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1 ml-2 space-y-2 border-l-2 pl-4">
          <Detail title="Input" value={JSON.stringify(tool.args, null, 2)} />
          {tool.output !== undefined && <Detail title="Output" value={formatValue(tool.output)} />}
          {tool.status === "error" && tool.output === undefined && (
            <p className="text-xs text-destructive">This step didn&apos;t finish.</p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function Detail({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted-foreground">{title}</div>
      <pre className="max-h-64 overflow-auto rounded-lg bg-muted/60 p-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {value}
      </pre>
    </div>
  );
}

function SubAgent({ block, streaming }: { block: SubAgentBlock; streaming: boolean }) {
  const [open, setOpen] = useState(true);
  const running = block.open && streaming;
  const name = humanize(block.name.replace(/^(sub-agent|supervisor)-/, ""));
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-xl border bg-muted/20">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
        <BotIcon className="size-4" />
        <span>
          {running ? "Working with" : "Delegated to"} <span className="font-medium text-foreground">{name}</span>
        </span>
        {running && <Loader2Icon className="size-3.5 animate-spin" />}
        <ChevronRightIcon className={cn("ml-auto size-3.5 transition-transform", open && "rotate-90")} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-t px-3 py-3">
          {block.blocks.length ? (
            <Blocks blocks={block.blocks} streaming={streaming} />
          ) : (
            <p className="text-sm text-muted-foreground">{running ? "Thinking…" : "No output."}</p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function TaskCard({ block }: { block: TaskBlock }) {
  const { task } = block;
  const status = task.state === "complete" ? (task.result === "error" ? "error" : "success") : "pending";
  const stateLabel =
    task.state === "complete"
      ? task.result === "error"
        ? "Failed"
        : "Done"
      : task.state === "running"
        ? "Running"
        : "Queued";
  const hasData = Object.keys(task.data ?? {}).length > 0;
  return (
    <div className="flex items-start gap-3 rounded-xl border px-3 py-2.5 text-sm">
      <div className="mt-0.5">
        <StatusIcon status={status} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-medium">{task.name ?? "Task"}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{stateLabel}</span>
        </div>
        {hasData && (
          <pre className="mt-1 overflow-x-auto font-mono text-xs text-muted-foreground">
            {JSON.stringify(task.data, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
