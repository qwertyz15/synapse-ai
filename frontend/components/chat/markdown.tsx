"use client";

import { CheckIcon, CopyIcon } from "lucide-react";
import { memo, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

type MdNode = { type: string; value?: string; children?: MdNode[]; data?: Record<string, unknown> };

const CITATION = /\(([^()\n]{2,80}?),\s*(?:page|p\.)\s*(\d+(?:\s*[-–]\s*\d+)?)\)/gi;
const SKIP = new Set(["link", "inlineCode", "code"]);

function splitCitations(node: MdNode) {
  if (!node.children) return;
  node.children = node.children.flatMap((child) => {
    if (SKIP.has(child.type)) return [child];
    if (child.type !== "text" || !child.value) {
      splitCitations(child);
      return [child];
    }
    const out: MdNode[] = [];
    let last = 0;
    for (const m of child.value.matchAll(CITATION)) {
      if (m.index > last) out.push({ type: "text", value: child.value.slice(last, m.index) });
      const source = m[1].trim().replace(/\.(pdf|docx|txt|md)$/i, "");
      out.push({
        type: "citation",
        data: { hName: "span", hProperties: { className: ["citation"], title: m[0].slice(1, -1) } },
        children: [{ type: "text", value: `${source} · p. ${m[2]}` }],
      });
      last = m.index + m[0].length;
    }
    if (!out.length) return [child];
    if (last < child.value.length) out.push({ type: "text", value: child.value.slice(last) });
    return out;
  });
}

const remarkCitations = () => (tree: MdNode) => splitCitations(tree);

function CodeBlock({ children, ...props }: React.ComponentProps<"pre">) {
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const child = Array.isArray(children) ? children[0] : children;
  const className = (child as { props?: { className?: string } })?.props?.className ?? "";
  const language = /language-([\w-]+)/.exec(className)?.[1] ?? "";

  const copy = async () => {
    await navigator.clipboard.writeText(ref.current?.textContent ?? "");
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border bg-muted/50">
      <div className="flex items-center justify-between border-b bg-muted/60 px-3 py-1.5 text-xs text-muted-foreground">
        <span>{language || "text"}</span>
        <button type="button" onClick={copy} className="flex items-center gap-1 hover:text-foreground">
          {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre ref={ref} {...props} className="overflow-x-auto p-3 font-mono text-[0.85em] leading-relaxed">
        {children}
      </pre>
    </div>
  );
}

const components: Components = {
  pre: ({ node: _node, ...props }) => <CodeBlock {...props} />,
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
};

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkCitations]}
        rehypePlugins={[[rehypeHighlight, { detect: false, ignoreMissing: true }]]}
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
