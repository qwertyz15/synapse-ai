# Web UI

A ChatGPT-style chat interface for the agent service, built with Next.js, Tailwind CSS and shadcn/ui.

## Run

From the repo root, `make run` starts the service and this UI together at http://localhost:3000.

To run the UI on its own against a service that's already running:

```sh
cp .env.example .env.local   # adjust AGENT_URL / AUTH_SECRET if needed
npm ci
npm run dev
```

## How it talks to the service

The browser only calls `/api/agent/*`. That route handler (`app/api/agent/[...path]/route.ts`)
forwards an allow-list of endpoints to `AGENT_URL`, adds the `AUTH_SECRET` bearer token, and
fills in `user_id` from an anonymous per-browser cookie, so secrets never reach the browser
and the service doesn't need CORS.

Streaming responses are parsed in `lib/sse.ts` and folded into chat turns by the pure reducer in
`lib/chat-reducer.ts`, which also renders saved history, so live and reloaded chats look the same.

## Checks

```sh
npm run lint
npx tsc --noEmit
npm test
npm run build
```
