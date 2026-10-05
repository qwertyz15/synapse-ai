import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { chatReducer, historyToTurns, turnText, type AssistantTurn, type Turn } from "../chat-reducer";
import { readEvents } from "../sse";
import type { ChatMessage, StreamEvent } from "../types";

const fixture = (name: string) => readFileSync(join(__dirname, "fixtures", `${name}.sse`), "utf8");

function streamOf(text: string, chunkSize: number): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) controller.enqueue(bytes.slice(i, i + chunkSize));
      controller.close();
    },
  });
}

async function collect(text: string, chunkSize = 7): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const e of readEvents(streamOf(text, chunkSize))) events.push(e);
  return events;
}

async function run(name: string): Promise<AssistantTurn> {
  let turns: Turn[] = chatReducer([], { type: "user", text: "q" });
  for (const event of await collect(fixture(name))) turns = chatReducer(turns, { type: "event", event });
  expect(turns).toHaveLength(2);
  return turns[1] as AssistantTurn;
}

describe("readEvents", () => {
  it("parses events regardless of chunk boundaries", async () => {
    const whole = await collect(fixture("research-assistant"), 1 << 20);
    const tiny = await collect(fixture("research-assistant"), 3);
    expect(tiny).toEqual(whole);
    expect(whole.at(-1)).toEqual({ type: "done" });
  });

  it("skips unknown lines instead of stopping", async () => {
    const events = await collect(
      ': keepalive\n\nevent: x\n\ndata: {"type":"token","content":"hi"}\n\ndata: [DONE]\n\n',
    );
    expect(events).toEqual([{ type: "token", content: "hi" }, { type: "done" }]);
  });
});

describe("chatReducer", () => {
  it("replaces streamed tokens with the final message", async () => {
    const turn = await run("chatbot");
    expect(turn.status).toBe("done");
    expect(turn.blocks).toHaveLength(1);
    expect(turn.blocks[0]).toMatchObject({ kind: "text" });
    expect(turn.blocks[0]).not.toHaveProperty("draft", true);
    expect(turn.runId).toBeTruthy();
  });

  it("resolves tool calls with their results", async () => {
    const turn = await run("research-assistant");
    const tools = turn.blocks.filter((b) => b.kind === "tool");
    expect(tools.length).toBeGreaterThan(0);
    for (const t of tools) expect(t).toMatchObject({ status: "success", output: expect.any(String) });
    expect(turnText(turn)).toMatch(/15/);
  });

  it("nests sub-agent work and surfaces backend errors", async () => {
    const turn = await run("langgraph-supervisor-agent");
    const sub = turn.blocks.find((b) => b.kind === "subagent");
    expect(sub).toMatchObject({ name: "math_expert", open: false });
    expect(sub && "blocks" in sub && sub.blocks.some((b) => b.kind === "tool" && b.name === "multiply")).toBe(true);
    expect(turnText(turn)).not.toMatch(/Transferring back/);
    expect(turn.status).toBe("error");
    expect(turn.error).toBe("Internal server error");
  });

  it("upserts background task cards by run id", async () => {
    const turn = await run("bg-task-agent");
    const tasks = turn.blocks.filter((b) => b.kind === "task");
    const ids = new Set(tasks.map((t) => t.kind === "task" && t.task.run_id));
    expect(tasks.length).toBe(ids.size);
    expect(tasks.length).toBeGreaterThan(0);
  });

  it("opens one placeholder turn on send that fills with the response", () => {
    let turns: Turn[] = chatReducer([], { type: "user", text: "q" });
    turns = chatReducer(turns, { type: "start" });
    expect(chatReducer(turns, { type: "start" })).toBe(turns);
    expect(turns[1]).toMatchObject({ role: "assistant", status: "streaming", blocks: [] });

    turns = chatReducer(turns, { type: "event", event: { type: "token", content: "hi" } });
    expect(turns).toHaveLength(2);
    expect((turns[1] as AssistantTurn).blocks).toEqual([{ kind: "text", text: "hi", draft: true }]);
  });

  it("settles the placeholder when the request fails before any response", () => {
    let turns: Turn[] = chatReducer([], { type: "user", text: "q" });
    turns = chatReducer(turns, { type: "start" });
    turns = chatReducer(turns, { type: "failed", error: "Service unavailable" });
    expect(turns).toHaveLength(2);
    expect(turns[1]).toMatchObject({ status: "error", error: "Service unavailable", blocks: [] });
  });

  it("keeps the placeholder last when the stream echoes a human message", () => {
    let turns: Turn[] = chatReducer([], { type: "user", text: "q" });
    turns = chatReducer(turns, { type: "start" });
    turns = chatReducer(turns, {
      type: "event",
      event: { type: "message", content: { type: "human", content: "q2" } },
    });
    expect(turns.map((t) => t.role)).toEqual(["user", "user", "assistant"]);
    expect(turns[2]).toMatchObject({ status: "streaming", blocks: [] });
  });

  it("marks pending tools as failed when stopped", () => {
    let turns: Turn[] = chatReducer([], { type: "user", text: "q" });
    const msg: ChatMessage = { type: "ai", content: "", tool_calls: [{ name: "Calculator", args: {}, id: "c1" }] };
    turns = chatReducer(turns, { type: "event", event: { type: "message", content: msg } });
    turns = chatReducer(turns, { type: "event", event: { type: "token", content: "partial" } });
    turns = chatReducer(turns, { type: "stopped" });
    const turn = turns[1] as AssistantTurn;
    expect(turn.status).toBe("stopped");
    expect(turn.blocks).toEqual([
      expect.objectContaining({ kind: "tool", status: "error" }),
      { kind: "text", text: "partial", draft: false },
    ]);
  });
});

describe("historyToTurns", () => {
  it("renders history the same way as a live stream", async () => {
    const events = await collect(fixture("research-assistant"));
    const messages = events.flatMap((e) => (e.type === "message" ? [e.content] : []));
    const turns = historyToTurns([{ type: "human", content: "q" }, ...messages]);
    const live = await run("research-assistant");
    expect(turns).toHaveLength(2);
    const { id: _a, ...fromHistory } = turns[1] as AssistantTurn;
    const { id: _b, ...fromLive } = live;
    expect(fromHistory).toEqual(fromLive);
  });
});
