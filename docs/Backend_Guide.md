# Backend guide

A tour of the Python backend in `src/`: what each file does and how a chat message travels through it.

## How a message flows

When you send a message in the web UI:

1. The web UI's proxy calls `POST /research-assistant/stream` on the service, adding the service
   token, your anonymous `user_id` and (only if the GitHub connector is on) your GitHub token.
2. `service/service.py` records the chat in the app database (or refuses it if the thread belongs
   to someone else), then builds the run: the chat's `thread_id` and `user_id` go into the LangGraph
   config, and the GitHub token goes into a separate run context that is never saved.
3. The agent graph (`agents/research_assistant.py`) loads the chat's history from the checkpointer
   (`memory/`), adds its instructions, and calls the model (`core/llm.py`).
4. If the model asks for tools, they run (`agents/tools.py`, `agents/github_tools.py`). Document
   search reads Qdrant (`ingestion/`), then the model is called again with the results.
5. Each new message is saved to the checkpointer and streamed back as Server-Sent Events: tokens
   while the model writes, then the full messages, then `[DONE]`.

## Entry points

| File | What it does |
|---|---|
| `run_service.py` | Starts the FastAPI service with uvicorn on `HOST:PORT` (default `127.0.0.1:8080`). This is what `make run` (via `scripts/run_local.sh`) and the Docker image run. |
| `run_agent.py` | Runs one agent directly in the terminal, without the service. Handy for quick experiments. |
| `run_client.py` | Examples of calling the running service with the Python `AgentClient` (sync, async, streaming). |
| `streamlit_app.py` | The legacy Streamlit chat UI, which talks to the service through `AgentClient`. |
| `pages/Documents.py` | Streamlit's Documents page for uploading and deleting library files. |

## `service/` — the HTTP API

| File | What it does |
|---|---|
| `service.py` | The FastAPI app. On startup (`lifespan`) it opens the checkpointer and store and loads every agent. Endpoints: `/{agent}/invoke` (one reply), `/{agent}/stream` (SSE streaming), `/{agent}/history`, `/{agent}/threads` and `/chats` (list chats, from the app database), `DELETE /{agent}/threads/{id}` (delete a chat and its files), `/info` (agents and models), `/feedback` (LangSmith). `verify_bearer` enforces `AUTH_SECRET`; `github_access` reads the `X-GitHub-*` headers; `_run_context` turns them into the agent's run context; `_handle_input` builds the LangGraph config and resumes interrupted runs. |
| `rag.py` | Document endpoints. `/rag/documents` uploads, lists and deletes **library** files (saved to `data/` and indexed). `/rag/attachments` attaches, lists and removes files for **one chat**. Uploads are validated (type, 25 MB limit, safe names) and indexing runs behind one lock. |
| `threads.py` | `thread_owner`: which user and agent a thread belongs to according to the checkpointer, for chats the app database doesn't know yet. |
| `agui.py` | Serves the agents over the AG-UI protocol at `/agui/{agent}/run`, for AG-UI frontends such as CopilotKit. |
| `utils.py` | Converts LangChain messages to the API's `ChatMessage` format (including the attachment names on your messages), reads messages out of checkpoints, and checks a requested model is available. |

## `agents/` — the AI agents and tools

| File | What it does |
|---|---|
| `agents.py` | The registry: every agent's key, description and graph. `get_agent` and `load_agent` look them up; `DEFAULT_AGENT` is `research-assistant`. Register new agents here. |
| `research_assistant.py` | The main agent. A LangGraph graph: safety check → model ↔ tools → answer. Each call rebuilds its instructions (date, library files, this chat's attachments, GitHub status) and binds the base tools plus GitHub tools when the run has a GitHub token. |
| `rag_assistant.py` | Like the research assistant, but its only tool is document search. |
| `tools.py` | Tool definitions. `Calculator` (numexpr) and `DocumentSearch`, which searches this chat's attachments plus the library and labels each passage with its file and page. |
| `github_tools.py` | GitHub MCP tools shared by agents. `AgentContext` holds the per-run token, login and write flag. Tools are listed once without credentials; the `_authorize` interceptor adds the caller's token and the read-only header to every call. Limits GitHub to the repos, issues, pull-requests and context toolsets. |
| `github_mcp_agent/github_mcp_agent.py` | The dedicated GitHub agent (API only now; the connector replaces it in the web UI). |
| `safeguard.py` | Content moderation with LlamaGuard on Groq. Skipped (treated as safe) when `GROQ_API_KEY` isn't set. |
| `lazy_agent.py` | Base class for agents that need async setup at startup, such as loading MCP tools. |
| `utils.py` | Shared helpers: `handle_tool_error` turns tool exceptions into a message the model can react to; `CustomData` sends custom stream events. |
| `chatbot.py` | The simplest agent: one model call, no tools. |
| `bg_task_agent/` | Demo: reports progress of fake background tasks as live task cards (`task.py`). |
| `interrupt_agent.py` | Demo: pauses with `interrupt()` to ask for your birth date, then resumes. |
| `command_agent.py` | Demo: LangGraph `Command` routing between nodes, no model. |
| `langgraph_supervisor_agent.py`, `langgraph_supervisor_hierarchy_agent.py` | Demos: a supervisor delegating to math and research sub-agents, flat or nested. |
| `knowledge_base_agent.py` | Retrieval from an Amazon Bedrock Knowledge Base (needs AWS setup). |

## `ingestion/` — turning documents into searchable chunks

| File | What it does |
|---|---|
| `pipeline.py` | `run_ingestion`: syncs the vector store with the `data/` folder. Only new or changed files are embedded; deleted files are removed. Rebuilds everything if the embedding model changed. |
| `loader.py` | Finds supported files (`.pdf`, `.docx`, `.txt`, `.md`) in a folder and hashes them to detect changes. |
| `parsers.py` | Extracts text: pypdf for PDFs (page by page), docx2txt for Word, a plain read for text and Markdown. |
| `cleaning.py` | Normalizes text: unicode, joined hyphenated words, extra spaces and blank lines. |
| `chunking.py` | Splits text into ~2,000-character chunks with 500 overlap and attaches metadata (file, page, hash). |
| `vectors.py` | `VectorStore`: one Qdrant collection (server via `QDRANT_URL`, or embedded in `QDRANT_PATH`), on-disk vectors, batched writes, filtered search. |
| `index.py` | The shared library collection and helpers to replace or re-tag a document's chunks. |
| `jobs.py` | Runs one upload as a job (queued → indexing → ready/failed), shared by the worker and inline indexing. |
| `parse_worker.py` | Parses an uploaded file in a separate, time- and memory-limited process. |
| `attachments.py` | Chat attachments in their own `chat_attachments` collection, tagged with `thread_id` and `user_id`: add, list, delete, delete-all-for-a-chat and scoped search. |
| `manifest.py` | Which library files are indexed (hash, chunk count, time), in the `library_documents` table. Imports the older `chroma_db/ingestion_manifest.sqlite` once if present. |
| `changes.py` | Compares files with the manifest to find new, updated, unchanged and deleted ones. |
| `models.py` | Small dataclasses used across the pipeline (source document, parsed page, change set, report). |

## `db/` — the app database (SQLAlchemy)

| File | What it does |
|---|---|
| `engine.py` | Picks the database (`APP_DATABASE_URL`, else `sqlite:///app.db`, or Postgres when `DATABASE_TYPE=postgres`), creates the async engine for the service and a sync one for ingestion, and applies Alembic migrations on first use. |
| `models.py` | The tables: `chats` (owner, agent, title, created/updated), `chat_attachments`, `library_documents` and `app_meta`. |
| `chats.py` | Queries used by the service: claim a chat on each message (creates it, bumps `updated_at`, refuses other users), list chats per agent or across agents, attachment rows, delete. |
| `backfill.py` | One-time imports at startup: chats from existing checkpoints and attachments already in the vector store, so data from before the app database isn't lost. |
| `migrations/` | Alembic migrations. Create new ones with `uv run alembic revision --autogenerate -m "..."` after changing `models.py`. |

## `memory/` — where chats are saved

| File | What it does |
|---|---|
| `__init__.py` | Picks the backend from `DATABASE_TYPE`: `initialize_database` (the checkpointer, i.e. chat history) and `initialize_store` (long-term memory). |
| `sqlite.py` | The default: chats in `checkpoints.db`; the store is in memory only. |
| `postgres.py` | Postgres checkpointer and store, configured from the `POSTGRES_*` settings. |
| `mongodb.py` | MongoDB checkpointer, configured from the `MONGO_*` settings. |

## `core/` — settings and models

| File | What it does |
|---|---|
| `settings.py` | Every setting, read from `.env` with Pydantic: API keys, default model, embeddings, RAG paths, GitHub, database, auth. Also works out which models are available from the keys you set. |
| `llm.py` | `get_model(name)` creates the chat model for any supported provider (OpenAI, DeepSeek, Anthropic, Google, Groq, Bedrock, Ollama, OpenRouter, OpenAI-compatible), cached per name. `FakeToolModel` backs `USE_FAKE_MODEL`. |
| `embeddings.py` | `get_embeddings()` for document search (OpenAI or Voyage). `embedding_signature` changes when the provider or model changes, triggering a full re-index. |

## `schema/` — data shapes

| File | What it does |
|---|---|
| `schema.py` | Request and response models: `UserInput`/`StreamInput` (message, thread, model, attachments), `ChatMessage`, history and thread types, library and attachment results. |
| `models.py` | The model catalog: every provider and model name the service can offer. |
| `task_data.py` | The payload behind background-task progress events. |

## `client/` and `voice/`

| File | What it does |
|---|---|
| `client/client.py` | `AgentClient`: a Python client for the service (invoke, stream, history, threads, feedback, documents), sync and async. Sends `AUTH_SECRET` if set. |
| `voice/` | Optional speech for the Streamlit app: `stt.py` and `tts.py` choose a provider, `providers/` implements OpenAI speech-to-text and text-to-speech, and `manager.py` wires them into the UI. |

## Where data lives

| What | Where | Written by |
|---|---|---|
| Chat messages and tool results | `checkpoints.db` (or Postgres/MongoDB) | the checkpointer in `memory/` |
| Library files | `data/` | `service/rag.py` uploads, or you |
| Library chunks and embeddings | Qdrant, collection `rag_documents` | `ingestion/pipeline.py` |
| Chat attachment chunks | Qdrant, collection `chat_attachments` | `ingestion/attachments.py` |
| Users' own library chunks | Qdrant, collection `user_library` | `ingestion/user_library.py` |
| Chat list (owner, title, times) and attachment rows | `app.db` (or Postgres), tables `chats`, `chat_attachments` | `db/chats.py` |
| Which library files are indexed | `app.db` (or Postgres), table `library_documents` | `ingestion/manifest.py` |
| GitHub tokens | nowhere on the server; an encrypted cookie in the browser | the web UI |

## Where to change common things

| To… | Edit |
|---|---|
| Add a new agent | a new file in `agents/`, then register it in `agents/agents.py` |
| Add a tool to the research assistant | `agents/tools.py`, then the `tools` list in `agents/research_assistant.py` |
| Change the assistant's instructions | `build_instructions` in `agents/research_assistant.py` |
| Change chunk size or how many passages a search returns | `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` in `.env`; `k` in `agents/tools.py` and `ingestion/attachments.py` |
| Support a new file type | `ingestion/loader.py` (extensions) and `ingestion/parsers.py` |
| Add a model or provider | `schema/models.py` and `core/llm.py` |
| Add an API endpoint | `service/service.py`, or `service/rag.py` for document endpoints |
| Add or change an app table | `db/models.py`, then `uv run alembic revision --autogenerate -m "..."` |
