"use client";

import { FileTextIcon, Loader2Icon, MenuIcon, PanelLeftIcon, Trash2Icon, UploadCloudIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useApp } from "@/components/app-provider";
import { IconButton } from "@/components/icon-button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { deleteDocument, listDocuments, uploadDocuments } from "@/lib/api";
import type { IngestionResult, RagDocument } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPT = [".pdf", ".docx", ".txt", ".md"];
const MAX_BYTES = 25 * 1024 * 1024;

function summarize(r: IngestionResult): string {
  const parts = [
    r.new.length && `${r.new.length} added`,
    r.updated.length && `${r.updated.length} updated`,
    r.unchanged.length && `${r.unchanged.length} unchanged`,
    r.deleted.length && `${r.deleted.length} removed`,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : "Nothing changed";
}

export default function DocumentsPage() {
  const { sidebarOpen, setSidebarOpen, setMobileNavOpen } = useApp();
  const [docs, setDocs] = useState<RagDocument[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [problems, setProblems] = useState<[string, string][]>([]);
  const [pendingDelete, setPendingDelete] = useState<RagDocument | null>(null);
  const [deleting, setDeleting] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    listDocuments()
      .then((d) => {
        setDocs(d);
        setLoadError(null);
      })
      .catch((err: Error) => setLoadError(err.message));
  }, []);

  useEffect(refresh, [refresh]);

  const upload = async (files: File[]) => {
    if (!files.length || uploading) return;
    const tooBig = files.filter((f) => f.size > MAX_BYTES);
    const ok = files.filter((f) => f.size <= MAX_BYTES);
    const local: [string, string][] = tooBig.map((f) => [f.name, "larger than 25 MB"]);
    setProblems(local);
    if (!ok.length) return;
    setUploading(true);
    try {
      const result = await uploadDocuments(ok);
      setProblems([...local, ...Object.entries(result.rejected), ...Object.entries(result.failed)]);
      toast.success(`${summarize(result)} · ${result.chunks_written} chunks indexed`);
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteDocument(pendingDelete.doc_id);
      toast.success(`Removed ${pendingDelete.doc_id}`);
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-1 px-2">
        <IconButton label="Open menu" className="md:hidden" onClick={() => setMobileNavOpen(true)}>
          <MenuIcon />
        </IconButton>
        {!sidebarOpen && (
          <IconButton label="Open sidebar" className="hidden md:inline-flex" onClick={() => setSidebarOpen(true)}>
            <PanelLeftIcon />
          </IconButton>
        )}
        <h1 className="px-2.5 text-base font-semibold">Documents</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-8 px-4 pt-4 pb-12">
          <p className="text-sm text-muted-foreground">
            Files here are indexed for the Research and RAG assistants, which search them to answer your questions.
          </p>

          <div
            role="button"
            tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              upload(Array.from(e.dataTransfer.files));
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging ? "border-primary bg-muted" : "hover:bg-muted/50",
              uploading && "pointer-events-none opacity-70",
            )}
          >
            {uploading ? (
              <Loader2Icon className="size-8 animate-spin text-muted-foreground" />
            ) : (
              <UploadCloudIcon className="size-8 text-muted-foreground" />
            )}
            <p className="font-medium">
              {uploading ? "Uploading and indexing…" : "Drop files here or click to upload"}
            </p>
            <p className="text-xs text-muted-foreground">PDF, DOCX, TXT or Markdown · up to 25 MB each</p>
            <input
              ref={input}
              type="file"
              multiple
              accept={ACCEPT.join(",")}
              className="hidden"
              onChange={(e) => upload(Array.from(e.target.files ?? []))}
            />
          </div>

          {problems.length > 0 && (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm">
              <p className="mb-1 font-medium text-destructive">Some files weren&apos;t indexed</p>
              <ul className="space-y-0.5 text-muted-foreground">
                {problems.map(([name, reason]) => (
                  <li key={name}>
                    <span className="text-foreground">{name}</span>: {reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <section>
            <h2 className="mb-3 text-sm font-medium">Indexed documents{docs ? ` (${docs.length})` : ""}</h2>
            {loadError ? (
              <div className="flex items-center justify-between gap-3 rounded-xl border p-4 text-sm">
                <span className="text-destructive">{loadError}</span>
                <Button variant="outline" size="sm" onClick={refresh}>
                  Retry
                </Button>
              </div>
            ) : docs === null ? (
              <div className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-14 rounded-xl" />
                ))}
              </div>
            ) : docs.length === 0 ? (
              <p className="rounded-xl border p-6 text-center text-sm text-muted-foreground">
                No documents yet. Upload one to get started.
              </p>
            ) : (
              <ul className="divide-y rounded-xl border">
                {docs.map((d) => (
                  <li key={d.doc_id} className="flex items-center gap-3 px-4 py-3">
                    <FileTextIcon className="size-5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{d.doc_id}</p>
                      <p className="text-xs text-muted-foreground">
                        {d.file_type.toUpperCase()} · {d.chunk_count} chunks · added{" "}
                        {new Date(d.ingested_at).toLocaleString()}
                      </p>
                    </div>
                    <IconButton label="Delete" size="icon-sm" onClick={() => setPendingDelete(d)}>
                      <Trash2Icon />
                    </IconButton>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this document?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete?.doc_id} will be removed from the data folder and the search index. This can&apos;t be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
