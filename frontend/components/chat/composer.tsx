"use client";

import { ArrowUpIcon, ChevronDownIcon, SquareIcon } from "lucide-react";
import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";

import { useApp } from "@/components/app-provider";
import { AttachMenu, AttachmentChips, ChatFilesButton, ConnectorChips } from "@/components/chat/attach-menu";
import type { ChatAttachments } from "@/components/chat/use-chat-attachments";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export type ComposerHandle = { focus: () => void };

type Props = {
  agent: string;
  chat: ChatAttachments;
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  disabled?: boolean;
  placeholder?: string;
};

export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { agent, chat, onSend, onStop, streaming, disabled, placeholder = "Ask anything" },
  ref,
) {
  const [text, setText] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => textarea.current?.focus() }));

  useLayoutEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [text]);

  const canSend = text.trim().length > 0 && !streaming && !disabled;

  const submit = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="rounded-3xl border bg-background shadow-sm transition-shadow focus-within:shadow-md dark:bg-muted/40"
    >
      <AttachmentChips chat={chat} />
      <textarea
        ref={textarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        rows={1}
        autoFocus
        placeholder={placeholder}
        aria-label="Message"
        className="block max-h-60 w-full resize-none bg-transparent px-5 pt-4 pb-2 text-base outline-none placeholder:text-muted-foreground"
      />
      <div className="flex items-center justify-between gap-2 px-3 pb-3">
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          <AttachMenu agent={agent} chat={chat} />
          <ChatFilesButton chat={chat} />
          <ConnectorChips agent={agent} />
          <ModelPicker />
        </div>
        {streaming ? (
          <Button type="button" size="icon" className="rounded-full" onClick={onStop} aria-label="Stop generating">
            <SquareIcon className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button type="submit" size="icon" className="rounded-full" disabled={!canSend} aria-label="Send message">
            <ArrowUpIcon />
          </Button>
        )}
      </div>
    </form>
  );
});

function ModelPicker() {
  const { info, model, setModel } = useApp();
  if (!info || info.models.length === 0) return <span />;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button type="button" variant="ghost" size="sm" className="rounded-full text-muted-foreground" />}
      >
        {model}
        <ChevronDownIcon />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuRadioGroup value={model} onValueChange={(v) => setModel(v as string)}>
          <DropdownMenuLabel>Model</DropdownMenuLabel>
          {info.models.map((m) => (
            <DropdownMenuRadioItem key={m} value={m}>
              {m}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
