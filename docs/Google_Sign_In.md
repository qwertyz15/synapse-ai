# Google sign-in

Synapse runs without accounts by default: each browser gets an anonymous identity. For a deployment
other people use, turn on Google sign-in so everyone has a real account, you decide who may join,
and you (and anyone else in `ADMIN_EMAILS`) are recognised as admins.

## 1. Create a Google OAuth client

1. Open the [Google Cloud console](https://console.cloud.google.com/) and create (or pick) a project.
2. **APIs & Services → OAuth consent screen**: choose **External**, fill in the app name (Synapse),
   support email and developer email. The default scopes are enough (`openid`, `email`, `profile`).
   While the app is in **Testing**, only the test users you add there can sign in; **Publish** it
   when you're ready for everyone.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized redirect URIs: add every address people will use, followed by `/api/auth/callback`:
     - `http://localhost:3000/api/auth/callback` for local use
     - `https://your-domain.com/api/auth/callback` for your deployment
4. Copy the **Client ID** and **Client secret**.

## 2. Configure Synapse

In `.env`:

```env
AUTH_ENABLED=true
GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
WEB_SESSION_SECRET=...            # openssl rand -base64 32, if you don't have one yet
ADMIN_EMAILS=you@gmail.com        # always allowed in, and admins

SIGNUPS=open                      # open | invite | closed
ALLOWED_EMAILS=                   # for invite: friend@gmail.com,@bracu.ac.bd
```

Restart Synapse (`make run`, or `make up` for Docker). Every page now asks you to sign
in first.

| `SIGNUPS` | Who can create an account |
|---|---|
| `open` | Anyone with a Google account |
| `invite` | Only addresses in `ALLOWED_EMAILS`; an entry like `@bracu.ac.bd` allows a whole domain |
| `closed` | Nobody new; existing accounts keep working |

`ADMIN_EMAILS` are always allowed, whatever `SIGNUPS` says, so you can't lock yourself out.

## Plans

Every account has a plan that decides how it can use the model keys in your `.env`:

| Plan | Who | Messages | Models | Uploads |
|---|---|---|---|---|
| **Admin** | Everyone in `ADMIN_EMAILS` | No limit | All | 25 MB per file, no file cap |
| **Unlimited** | Accounts you give it to | No limit | All | 25 MB per file, no file cap |
| **Free** | New accounts by default | `FREE_MESSAGES_PER_DAY` per UTC day | `FREE_MODELS` (all if empty) | `FREE_MAX_FILE_MB` per file, `FREE_LIBRARY_FILES` in the library |

```env
DEFAULT_PLAN=free              # or unlimited, e.g. for a private invite-only deployment
FREE_MESSAGES_PER_DAY=20
FREE_MODELS=deepseek-v4-flash  # comma-separated; empty allows every model
FREE_MAX_FILE_MB=5
FREE_LIBRARY_FILES=10
```

Users see their plan and today's usage in the sidebar's account menu, the model menu only lists
what their plan allows, and a clear message appears when the day's messages are used up. Requests
without an account (sign-in off) aren't limited.

## Admin page

Admins open **Admin** from the account menu to see every account with its plan, today's usage,
daily limit, saved key providers and last activity, and to:

- switch an account between **Free** and **Unlimited**,
- give one account its own **daily limit** (leave it empty for the plan's default),
- **block** or unblock an account: blocked accounts can't sign in, chat or upload.

Changes apply immediately. Admins come from `ADMIN_EMAILS`, which is checked on every request, so
they can't be blocked or demoted from the page; edit `ADMIN_EMAILS` and restart instead.

## Your own API keys

With `USER_KEYS_SECRET` set, signed-in users can open **Settings** (in the account menu) and add
their own key for OpenAI, Anthropic, DeepSeek, Google Gemini, Groq or OpenRouter:

- Chats on that provider's models then run on **their** key, so they don't use your credits, don't
  count toward their daily limit and aren't limited to `FREE_MODELS`.
- Models from a provider you have no key for become available to that user once they add theirs.
- Each key is checked with one free request to the provider before it's saved, stored encrypted
  (AES-GCM) and never shown again, only its last four characters. It's used only while that user's
  request runs and is never written to chat history or logs.

```env
USER_KEYS_SECRET=...   # openssl rand -base64 32; keep it stable, or saved keys stop working
```

## How it works

- Google OAuth runs in the web UI with state and PKCE. After Google confirms who you are, the web
  server asks the agent service to create or update your account (`POST /auth/sign-in`, protected by
  `AUTH_SECRET`); the service applies the sign-up rules.
- Your session is an encrypted, httpOnly cookie that lasts 30 days. **Sign out** is in the sidebar's
  account menu.
- Chats, your library, attachments and rate limits all belong to your account instead of the browser.
- Chats and files made in the same browser before sign-in was turned on move into your account the
  first time you sign in there. If a library file name clashes, your account's copy is kept.
- With `AUTH_ENABLED=false` (the default), nothing changes: there's no login and no accounts.

## Troubleshooting

- **"redirect_uri_mismatch" from Google**: the address in your browser plus `/api/auth/callback`
  must be listed exactly in the OAuth client's redirect URIs. Behind a proxy that hides the public
  address, set `GOOGLE_REDIRECT_URI` to the public callback URL.
- **"invite-only" message**: the account isn't in `ALLOWED_EMAILS` (or `SIGNUPS=closed`). Add it,
  restart Synapse (the lists are read at startup) and try again.
- **Signed out after a restart**: `WEB_SESSION_SECRET` changed, so old cookies can't be read. Keep it
  the same across restarts.
