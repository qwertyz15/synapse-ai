"use client";

import { ServerCrashIcon } from "lucide-react";

import { useApp } from "@/components/app-provider";
import { Button } from "@/components/ui/button";

export function ServiceError({ message }: { message: string }) {
  const { retryInfo } = useApp();
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <ServerCrashIcon className="size-10 text-muted-foreground" />
      <h1 className="text-lg font-semibold">Can&apos;t reach the agent service</h1>
      <p className="max-w-md text-sm text-muted-foreground">{message}</p>
      <p className="max-w-md text-sm text-muted-foreground">
        Start it with <code className="rounded bg-muted px-1.5 py-0.5">./run.sh</code> and try again.
      </p>
      <Button variant="outline" onClick={retryInfo}>
        Try again
      </Button>
    </div>
  );
}
