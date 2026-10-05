"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { attachToChat, detachFromChat, listAttachments } from "@/lib/api";
import type { ChatAttachment } from "@/lib/types";

const MAX_BYTES = 25 * 1024 * 1024;

export type ChatAttachments = {
  /** Every file attached to the chat; all of them stay searchable for the whole conversation. */
  attachments: ChatAttachment[];
  /** Attached since the last message was sent; shown in the composer and sent with the next message. */
  unsent: ChatAttachment[];
  pending: string[];
  attach: (files: File[]) => Promise<void>;
  detach: (name: string) => Promise<void>;
  markSent: (names: string[]) => void;
};

export function useChatAttachments(threadId: string, isNew: boolean, initiallySent: string[]): ChatAttachments {
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [pending, setPending] = useState<string[]>([]);
  const [sent, setSent] = useState(() => new Set(initiallySent));

  useEffect(() => {
    if (isNew) return;
    let cancelled = false;
    listAttachments(threadId)
      .then((list) => !cancelled && setAttachments(list))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [threadId, isNew]);

  const attach = useCallback(
    async (files: File[]) => {
      for (const f of files.filter((f) => f.size > MAX_BYTES)) toast.error(`${f.name}: larger than 25 MB`);
      const ok = files.filter((f) => f.size <= MAX_BYTES);
      if (!ok.length) return;
      const names = ok.map((f) => f.name);
      setPending((p) => [...p, ...names]);
      try {
        const result = await attachToChat(threadId, ok);
        setAttachments(result.attachments);
        // A re-attached file is new content, so it goes out with the next message again.
        setSent((s) => new Set([...s].filter((n) => !result.attached.includes(n))));
        for (const [name, reason] of Object.entries({ ...result.rejected, ...result.failed })) {
          toast.error(`${name}: ${reason}`);
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Couldn't attach the file");
      } finally {
        setPending((p) => p.filter((n) => !names.includes(n)));
      }
    },
    [threadId],
  );

  const detach = useCallback(
    async (name: string) => {
      try {
        setAttachments(await detachFromChat(threadId, name));
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Couldn't remove the file");
      }
    },
    [threadId],
  );

  const markSent = useCallback((names: string[]) => setSent((s) => new Set([...s, ...names])), []);
  const unsent = useMemo(() => attachments.filter((a) => !sent.has(a.name)), [attachments, sent]);

  return { attachments, unsent, pending, attach, detach, markSent };
}
