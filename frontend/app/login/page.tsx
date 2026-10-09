import { SynapseLogo } from "@/components/logo";

const ERRORS: Record<string, string> = {
  not_allowed: "This Synapse is invite-only, and your Google account isn't on the list.",
  unverified: "Your Google account's email address isn't verified.",
  blocked: "This account has been blocked. Contact the person who runs this Synapse.",
  denied: "Sign-in was cancelled.",
  expired: "The sign-in took too long or was opened in another browser. Please try again.",
  not_configured:
    "Google sign-in isn't set up on this server yet (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, WEB_SESSION_SECRET).",
  failed: "Couldn't sign you in. Please try again.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const returnTo = typeof params.returnTo === "string" ? params.returnTo : "/";
  const error = typeof params.error === "string" ? (ERRORS[params.error] ?? ERRORS.failed) : null;

  return (
    <main className="flex h-dvh flex-col items-center justify-center px-4">
      <div className="flex w-full max-w-sm flex-col items-center text-center">
        <SynapseLogo className="mb-6 size-14" />
        <h1 className="text-2xl font-semibold tracking-tight">Sign in to Synapse</h1>
        <p className="mt-2 text-sm text-muted-foreground">Your AI assistant for documents, the web and GitHub.</p>
        {error && (
          <p
            role="alert"
            className="mt-6 w-full rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        )}
        <a
          href={`/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`}
          className="mt-8 flex h-11 w-full items-center justify-center gap-3 rounded-full border bg-background text-sm font-medium shadow-sm transition-colors hover:bg-muted"
        >
          <GoogleMark />
          Continue with Google
        </a>
      </div>
    </main>
  );
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden>
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"
      />
    </svg>
  );
}
