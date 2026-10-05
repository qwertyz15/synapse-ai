import type { ChatMessage, StreamEvent, TaskData } from "./types";

export type TextBlock = { kind: "text"; text: string; draft?: boolean };
export type ToolBlock = {
  kind: "tool";
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "pending" | "success" | "error";
  output?: string;
};
export type TaskBlock = { kind: "task"; task: TaskData };
export type SubAgentBlock = {
  kind: "subagent";
  id: string;
  name: string;
  open: boolean;
  blocks: Block[];
};
export type Block = TextBlock | ToolBlock | TaskBlock | SubAgentBlock;

export type UserTurn = { id: string; role: "user"; text: string; attachments?: string[] };
export type AssistantTurn = {
  id: string;
  role: "assistant";
  blocks: Block[];
  status: "streaming" | "done" | "error" | "stopped";
  runId?: string;
  error?: string;
  errorCode?: string;
};
export type Turn = UserTurn | AssistantTurn;

export type ChatAction =
  | { type: "user"; text: string; attachments?: string[] }
  | { type: "event"; event: StreamEvent }
  | { type: "stopped" }
  | { type: "failed"; error: string; code?: string }
  | { type: "reset"; turns: Turn[] };

const TRANSFER_TO = "transfer_to_";
const TRANSFER_BACK = "transfer_back_to_";

let counter = 0;
const nextId = () => `t${Date.now().toString(36)}${(counter++).toString(36)}`;

function openContainer(blocks: Block[]): Block[] {
  const last = [...blocks].reverse().find((b): b is SubAgentBlock => b.kind === "subagent" && b.open);
  return last ? openContainer(last.blocks) : blocks;
}

function closeInnermost(blocks: Block[]): boolean {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.kind === "subagent" && b.open) {
      if (!closeInnermost(b.blocks)) b.open = false;
      return true;
    }
  }
  return false;
}

function findTool(blocks: Block[], id: string): ToolBlock | undefined {
  for (const b of blocks) {
    if (b.kind === "tool" && b.id === id) return b;
    if (b.kind === "subagent") {
      const found = findTool(b.blocks, id);
      if (found) return found;
    }
  }
}

function settle(blocks: Block[], toolStatus: "error" | null) {
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.kind === "text" && b.draft) {
      if (b.text) b.draft = false;
      else blocks.splice(i, 1);
    } else if (b.kind === "tool" && b.status === "pending" && toolStatus) {
      b.status = toolStatus;
    } else if (b.kind === "subagent") {
      b.open = false;
      settle(b.blocks, toolStatus);
    }
  }
}

function dropDraft(blocks: Block[]) {
  const last = blocks[blocks.length - 1];
  if (last?.kind === "text" && last.draft) blocks.pop();
}

function applyMessage(turn: AssistantTurn, msg: ChatMessage) {
  if (msg.run_id) turn.runId = msg.run_id;
  const target = openContainer(turn.blocks);

  if (msg.type === "ai") {
    dropDraft(target);
    const calls = msg.tool_calls ?? [];
    const handoffBack = calls.some((c) => c.name.startsWith(TRANSFER_BACK));
    if (msg.content && !handoffBack) target.push({ kind: "text", text: msg.content });
    for (const call of calls) {
      if (call.name.startsWith(TRANSFER_BACK)) {
        closeInnermost(turn.blocks);
      } else if (call.name.startsWith(TRANSFER_TO)) {
        target.push({
          kind: "subagent",
          id: call.id ?? nextId(),
          name: call.name.slice(TRANSFER_TO.length).replace(/^sub-agent-/, ""),
          open: true,
          blocks: [],
        });
      } else {
        target.push({ kind: "tool", id: call.id ?? nextId(), name: call.name, args: call.args, status: "pending" });
      }
    }
  } else if (msg.type === "tool") {
    const tool = msg.tool_call_id ? findTool(turn.blocks, msg.tool_call_id) : undefined;
    if (tool) {
      tool.status = msg.status === "error" ? "error" : "success";
      tool.output = msg.content;
    }
  } else if (msg.type === "custom") {
    const task = msg.custom_data as TaskData | undefined;
    if (!task?.run_id) return;
    const existing = target.find((b): b is TaskBlock => b.kind === "task" && b.task.run_id === task.run_id);
    if (existing) existing.task = task;
    else target.push({ kind: "task", task });
  }
}

function currentAssistant(turns: Turn[]): [Turn[], AssistantTurn] {
  const last = turns[turns.length - 1];
  if (last?.role === "assistant") {
    const copy = structuredClone(last);
    return [[...turns.slice(0, -1), copy], copy];
  }
  const turn: AssistantTurn = { id: nextId(), role: "assistant", blocks: [], status: "streaming" };
  return [[...turns, turn], turn];
}

export function chatReducer(turns: Turn[], action: ChatAction): Turn[] {
  switch (action.type) {
    case "reset":
      return action.turns;
    case "user":
      return [...turns, { id: nextId(), role: "user", text: action.text, attachments: action.attachments }];
    case "stopped":
    case "failed": {
      const [next, turn] = currentAssistant(turns);
      if (turn.status !== "streaming") return turns;
      settle(turn.blocks, "error");
      turn.status = action.type === "stopped" ? "stopped" : "error";
      if (action.type === "failed") {
        turn.error = action.error;
        turn.errorCode = action.code;
      }
      return next;
    }
    case "event": {
      const { event } = action;
      if (event.type === "message" && event.content.type === "human") {
        return chatReducer(turns, { type: "user", text: event.content.content });
      }
      const [next, turn] = currentAssistant(turns);
      if (event.type === "token") {
        if (!event.content) return turns;
        const target = openContainer(turn.blocks);
        const last = target[target.length - 1];
        if (last?.kind === "text" && last.draft) last.text += event.content;
        else target.push({ kind: "text", text: event.content, draft: true });
      } else if (event.type === "message") {
        applyMessage(turn, event.content);
      } else if (event.type === "error") {
        settle(turn.blocks, "error");
        turn.status = "error";
        turn.error = event.content;
      } else if (event.type === "done") {
        if (turn.status !== "streaming") return turns;
        settle(turn.blocks, "error");
        turn.status = "done";
      }
      return next;
    }
  }
}

export function historyToTurns(messages: ChatMessage[]): Turn[] {
  let turns: Turn[] = [];
  for (const m of messages) {
    if (m.type === "human") {
      turns = finishTurn(turns);
      const attachments = m.attachments?.length ? m.attachments : undefined;
      turns = chatReducer(turns, { type: "user", text: m.content, attachments });
    } else {
      turns = chatReducer(turns, { type: "event", event: { type: "message", content: m } });
    }
  }
  return finishTurn(turns);
}

function finishTurn(turns: Turn[]): Turn[] {
  const last = turns[turns.length - 1];
  if (last?.role !== "assistant" || last.status !== "streaming") return turns;
  const copy = structuredClone(last);
  settle(copy.blocks, "error");
  copy.status = "done";
  return [...turns.slice(0, -1), copy];
}

/**
 * Splits a turn into the work (tool calls, sub-agents, tasks and the notes written between them)
 * and the answer: the text after the last of those steps.
 */
export function splitWork(blocks: Block[]): { work: Block[]; answer: Block[] } {
  let last = -1;
  blocks.forEach((b, i) => {
    if (b.kind !== "text") last = i;
  });
  return { work: blocks.slice(0, last + 1), answer: blocks.slice(last + 1) };
}

/** The answer's text (what Copy copies); falls back to every text if there is no answer yet. */
export function turnText(turn: AssistantTurn): string {
  const collect = (blocks: Block[]): string[] =>
    blocks.flatMap((b) => (b.kind === "text" ? [b.text] : b.kind === "subagent" ? collect(b.blocks) : []));
  const { answer } = splitWork(turn.blocks);
  return collect(answer.length ? answer : turn.blocks).join("\n\n");
}
