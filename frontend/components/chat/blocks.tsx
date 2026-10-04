"use client";

import {
  BotIcon,
  CalculatorIcon,
  CheckIcon,
  ChevronRightIcon,
  CloudSunIcon,
  FileSearchIcon,
  GlobeIcon,
  Loader2Icon,
  WrenchIcon,
  XIcon,
} from "lucide-react";
import { useState } from "react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Block, SubAgentBlock, TaskBlock, ToolBlock } from "@/lib/chat-reducer";
import { cn } from "@/lib/utils";

import { Markdown } from "./markdown";

const TOOLS: Record<string, { icon: React.ElementType; running: string; done: string; arg?: string }> = {
  DocumentSearch: { icon: FileSearchIcon, running: "Searching documents", done: "Searched documents", arg: "query" },
  WebSearch: { icon: GlobeIcon, running: "Searching the web", done: "Searched the web", arg: "query" },
  Calculator: { icon: CalculatorIcon, running: "Calculating", done: "Calculated", arg: "expression" },
  Weather: { icon: CloudSunIcon, running: "Checking the weather", done: "Checked the weather", arg: "location" },
};

const humanize = (name: string) => {
  const s = name.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

export function Blocks({ blocks, streaming }: { blocks: Block[]; streaming: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "text":
            return <Markdown key={i} text={b.text} />;
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
  if (status === "error") return <XIcon className="size-3.5 text-destructive" />;
  return <CheckIcon className="size-3.5 text-emerald-600 dark:text-emerald-400" />;
}

function formatValue(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function ToolStep({ tool }: { tool: ToolBlock }) {
  const [open, setOpen] = useState(false);
  const meta = TOOLS[tool.name];
  const Icon = meta?.icon ?? WrenchIcon;
  const label = meta
    ? tool.status === "pending"
      ? meta.running
      : meta.done
    : `${tool.status === "pending" ? "Running" : "Ran"} ${humanize(tool.name)}`;
  const argValue = meta?.arg ? tool.args[meta.arg] : undefined;
  const summary = typeof argValue === "string" ? argValue : undefined;

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
