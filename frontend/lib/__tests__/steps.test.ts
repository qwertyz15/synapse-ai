import { describe, expect, it } from "vitest";

import { splitWork, turnText, type AssistantTurn, type Block, type ToolBlock } from "../chat-reducer";
import { summarizeWork, toolLabel } from "../steps";

const tool = (
  name: string,
  args: Record<string, unknown> = {},
  status: ToolBlock["status"] = "success",
): ToolBlock => ({
  kind: "tool",
  id: `${name}-${Math.random()}`,
  name,
  args,
  status,
});
const text = (t: string): Block => ({ kind: "text", text: t });

describe("splitWork", () => {
  it("keeps notes between steps in the work and the final text as the answer", () => {
    const blocks = [
      text("Let me look."),
      tool("search_repositories"),
      text("Reading READMEs."),
      tool("get_file_contents"),
      text("Here is the answer."),
    ];
    const { work, answer } = splitWork(blocks);
    expect(work).toHaveLength(4);
    expect(answer).toEqual([text("Here is the answer.")]);
  });

  it("treats a reply without steps as all answer", () => {
    expect(splitWork([text("Hi")])).toEqual({ work: [], answer: [text("Hi")] });
  });

  it("copies only the answer", () => {
    const turn: AssistantTurn = {
      id: "a",
      role: "assistant",
      status: "done",
      blocks: [text("Let me look."), tool("WebSearch"), text("Answer")],
    };
    expect(turnText(turn)).toBe("Answer");
  });
});

describe("summarizeWork", () => {
  it("groups many steps into one line", () => {
    const blocks = [
      tool("search_repositories", { query: "user:octo" }),
      ...Array.from({ length: 16 }, (_, i) => tool("get_file_contents", { path: `f${i}.md` })),
      tool("get_file_contents", { path: "x" }, "error"),
      tool("list_commits"),
      tool("list_commits"),
      tool("list_commits"),
    ];
    expect(summarizeWork(blocks, false)).toEqual({
      headline: "Searched repositories · Read 17 files · Listed commits ×3",
      steps: 21,
      active: false,
    });
  });

  it("shows the step in progress while streaming", () => {
    const blocks = [tool("search_repositories"), tool("get_file_contents", { path: "README.md" }, "pending")];
    expect(summarizeWork(blocks, true)).toMatchObject({ headline: "Reading “README.md”…", active: true });
  });

  it("describes a single step with its detail and caps long lists", () => {
    expect(summarizeWork([tool("DocumentSearch", { query: "PTO policy" })], false).headline).toBe(
      "Searched documents “PTO policy”",
    );
    const many = ["WebSearch", "Calculator", "Weather", "DocumentSearch", "get_me"].map((n) => tool(n));
    expect(summarizeWork(many, false).headline).toBe("Searched the web · Calculated · Checked the weather · +2 more");
  });

  it("labels unknown tools from their name and first string argument", () => {
    expect(toolLabel(tool("list_tags", { repo: "octo/app" }))).toEqual({ label: "Ran List tags", detail: "octo/app" });
  });
});
