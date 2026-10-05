import type { Block, ToolBlock } from "./chat-reducer";

type ToolMeta = {
  running: string;
  done: string;
  /** Argument shown next to the label, e.g. the search query or file path. */
  arg?: string;
  /** Summary grouping, e.g. "Read 16 files" instead of "Read ×16". */
  noun?: [singular: string, plural: string];
};

const TOOLS: Record<string, ToolMeta> = {
  DocumentSearch: { running: "Searching documents", done: "Searched documents", arg: "query" },
  WebSearch: { running: "Searching the web", done: "Searched the web", arg: "query" },
  Calculator: { running: "Calculating", done: "Calculated", arg: "expression" },
  Weather: { running: "Checking the weather", done: "Checked the weather", arg: "location" },
  search_repositories: { running: "Searching repositories", done: "Searched repositories", arg: "query" },
  search_code: { running: "Searching code", done: "Searched code", arg: "query" },
  get_file_contents: { running: "Reading", done: "Read", arg: "path", noun: ["file", "files"] },
  list_commits: { running: "Listing commits", done: "Listed commits", arg: "repo" },
  get_commit: { running: "Reading a commit", done: "Read", noun: ["commit", "commits"] },
  list_branches: { running: "Listing branches", done: "Listed branches", arg: "repo" },
  list_issues: { running: "Listing issues", done: "Listed issues", arg: "repo" },
  search_issues: { running: "Searching issues", done: "Searched issues", arg: "query" },
  issue_read: { running: "Reading an issue", done: "Read", noun: ["issue", "issues"] },
  get_issue: { running: "Reading an issue", done: "Read", noun: ["issue", "issues"] },
  list_pull_requests: { running: "Listing pull requests", done: "Listed pull requests", arg: "repo" },
  search_pull_requests: { running: "Searching pull requests", done: "Searched pull requests", arg: "query" },
  pull_request_read: { running: "Reading a pull request", done: "Read", noun: ["pull request", "pull requests"] },
  get_pull_request: { running: "Reading a pull request", done: "Read", noun: ["pull request", "pull requests"] },
  get_me: { running: "Checking your GitHub profile", done: "Checked your GitHub profile" },
  create_issue: { running: "Creating an issue", done: "Created an issue", arg: "title" },
  create_pull_request: { running: "Opening a pull request", done: "Opened a pull request", arg: "title" },
};

const humanize = (name: string) => {
  const s = name.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

function detailFor(tool: ToolBlock, meta: ToolMeta | undefined): string | undefined {
  const value = meta?.arg ? tool.args[meta.arg] : Object.values(tool.args).find((v) => typeof v === "string");
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/** "Read" + "README.md" for one step; `running` while the call is in flight. */
export function toolLabel(tool: ToolBlock): { label: string; detail?: string } {
  const meta = TOOLS[tool.name];
  const label = meta
    ? tool.status === "pending"
      ? meta.running
      : meta.done
    : `${tool.status === "pending" ? "Running" : "Ran"} ${humanize(tool.name)}`;
  return { label, detail: detailFor(tool, meta) };
}

function allTools(blocks: Block[]): ToolBlock[] {
  return blocks.flatMap((b) => (b.kind === "tool" ? [b] : b.kind === "subagent" ? allTools(b.blocks) : []));
}

const MAX_GROUPS = 3;

export type WorkSummary = {
  headline: string;
  steps: number;
  active: boolean;
};

/** One line describing everything the assistant did before answering. */
export function summarizeWork(blocks: Block[], streaming: boolean): WorkSummary {
  const tools = allTools(blocks);
  const pending = streaming ? tools.find((t) => t.status === "pending") : undefined;

  if (pending) {
    const { label, detail } = toolLabel(pending);
    return { headline: `${label}${detail ? ` “${detail}”` : ""}…`, steps: tools.length, active: true };
  }
  if (tools.length === 1) {
    const { label, detail } = toolLabel(tools[0]);
    return { headline: detail ? `${label} “${detail}”` : label, steps: 1, active: streaming };
  }

  const groups = new Map<string, number>();
  for (const t of tools) groups.set(t.name, (groups.get(t.name) ?? 0) + 1);
  const phrases = [...groups].map(([name, count]) => {
    const meta = TOOLS[name];
    if (meta?.noun) return `${meta.done} ${count} ${count === 1 ? meta.noun[0] : meta.noun[1]}`;
    const done = meta?.done ?? `Ran ${humanize(name)}`;
    return count > 1 ? `${done} ×${count}` : done;
  });
  const shown = phrases.slice(0, MAX_GROUPS).join(" · ");
  const more = phrases.length - MAX_GROUPS;
  const headline = tools.length ? `${shown}${more > 0 ? ` · +${more} more` : ""}` : streaming ? "Thinking…" : "Worked";
  return { headline, steps: tools.length, active: streaming };
}
