"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useApp } from "@/components/app-provider";
import { ChatView } from "@/components/chat/chat-view";
import { ServiceError } from "@/components/service-error";
import { newId } from "@/lib/api";

export default function NewChatPage() {
  const { agent, infoError } = useApp();
  const pathname = usePathname();
  const [threadId, setThreadId] = useState(newId);
  const previousPath = useRef(pathname);

  // A new chat rewrites the URL to /chat/... without remounting, so returning to "/" must start fresh.
  useEffect(() => {
    if (pathname === "/" && previousPath.current !== "/") setThreadId(newId());
    previousPath.current = pathname;
  }, [pathname]);

  if (infoError) return <ServiceError message={infoError} />;
  return <ChatView key={`${agent}:${threadId}`} agent={agent} threadId={threadId} isNew />;
}
