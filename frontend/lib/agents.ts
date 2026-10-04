const SUGGESTIONS: Record<string, string[]> = {
  "research-assistant": [
    "How many PTO days do I accrue by September if I started in March?",
    "Compare our parental leave policy with what US law (FMLA) requires",
    "Summarize the remote work policy and core hours",
    "What's the latest news in AI agents this week?",
  ],
  "rag-assistant": [
    "What leave types does the handbook list?",
    "Who do I contact for IT support?",
    "What are the company's core values?",
    "What does the security policy say about passwords?",
  ],
  chatbot: [
    "Explain LangGraph in two sentences",
    "Write a haiku about debugging",
    "Give me three ideas for a weekend project",
    "What's the difference between RAG and fine-tuning?",
  ],
  "langgraph-supervisor-agent": [
    "What is 23 times 47? Ask the math expert",
    "Research the population of Tokyo and divide it by 1000",
  ],
  "langgraph-supervisor-hierarchy-agent": [
    "What is 23 times 47? Ask the math expert",
    "Research the population of Tokyo and divide it by 1000",
  ],
  "bg-task-agent": ["Run the background task", "Start a long-running job and report progress"],
  "interrupt-agent": ["What's my zodiac sign?", "Tell me about my horoscope"],
  "command-agent": ["Hello! What can you do?", "Tell me a fun fact"],
  "github-mcp-agent": ["List the open issues in my repository", "Show the latest commits"],
  "knowledge-base-agent": ["What's in the knowledge base?", "Search the knowledge base for onboarding"],
};

export const suggestionsFor = (agent: string) =>
  SUGGESTIONS[agent] ?? ["Hello! What can you do?", "Tell me a fun fact"];

const ACRONYMS = new Set(["rag", "mcp", "bg"]);

export function agentLabel(key: string): string {
  return key
    .split("-")
    .map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)))
    .join(" ")
    .replace(/^BG Task/, "Background Task")
    .replace(/^Langgraph /, "");
}
