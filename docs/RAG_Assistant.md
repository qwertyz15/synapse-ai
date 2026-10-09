# Creating a RAG assistant

You can build a RAG assistant on a Qdrant vector store.

## Where vectors are stored

- **Qdrant server** when `QDRANT_URL` is set. Docker Compose runs one (`qdrant` service) and sets
  it; its memory cap is `QDRANT_MEMORY_LIMIT` (512 MB by default). Collections keep vectors, payload
  and the index on disk, so memory stays small.
- **Embedded store** in `QDRANT_PATH` (`./qdrant_data`) otherwise, e.g. for `make run`. Only one
  process can open it, so a separate ingestion worker needs the server.

Coming from an older version that used Chroma? Copy your data across once, without re-embedding:

```sh
python scripts/migrate_chroma_to_qdrant.py --dry-run   # see what would be copied
python scripts/migrate_chroma_to_qdrant.py
```

## Background indexing

Uploads from the Library and chat attachments become **jobs** (`ingestion_jobs` table): the file is
saved to `UPLOADS_DIR`, and with `REDIS_URL` set a Celery worker indexes it while the web UI shows
*Queued → Indexing… → ready* (or the error, with Retry). Without `REDIS_URL` the same code runs
during the upload request instead, which is fine for `make run` on your own machine.

Only the job id goes through Redis; the job's status lives in the app database. The worker imports
just the ingestion code (about 150 MB before the embedding client loads) and is kept within a memory
budget:

| Setting | Default | What it does |
|---|---|---|
| `WORKER_CONCURRENCY` | 1 | Jobs a worker runs at once |
| `WORKER_MAX_TASKS_PER_CHILD` | 50 | Jobs before a worker process is replaced |
| `WORKER_MAX_MEMORY_MB` | 700 | A process that grew past this is replaced after its job |
| `JOB_TIME_LIMIT_S` | 600 | Hard time limit per job |
| `JOB_MAX_RETRIES` | 3 | Retries for rate limits, timeouts and dropped connections (with backoff) |
| `WORKER_MEMORY_LIMIT` | 1g | Docker memory cap for the worker container |

A job that fails for good (e.g. a file with no readable text) keeps its file so it can be retried
or removed from the Library. If a worker dies mid-job, Redis hands the job to another worker after
20 minutes.

To run a worker without Docker, start Redis and Qdrant, set `REDIS_URL` and `QDRANT_URL` in `.env`,
and run `cd src && celery -A worker worker -Q ingestion`.

## Choosing an embedding provider

The database is built and searched with the same embedding model, configured in `.env`:

| Provider | Settings | Default model |
|---|---|---|
| OpenAI (default) | `OPENAI_API_KEY` | `text-embedding-ada-002` |
| [Voyage AI](https://www.voyageai.com/) | `EMBEDDING_PROVIDER=voyage`, `VOYAGE_API_KEY` | `voyage-4` |

Set `EMBEDDING_MODEL` to use a different model from the same provider. Vectors from different
models aren't compatible, so the ingestion pipeline automatically re-embeds everything when the
provider or model changes.

## Ingesting documents

The easiest way is the **Documents** page in the Streamlit app's sidebar. You can upload PDF,
Word, text and Markdown files there (up to 25 MB each), see what's indexed, and delete documents.
Uploads go through the service's `/rag/documents` API, which also works under Docker Compose,
where `./data` is mounted into the service container.

To ingest from the command line instead:

1. Put your documents in `./data` (or set `RAG_DATA_DIR`). PDF, Word (`.docx`), text (`.txt`) and
   Markdown (`.md`) files are supported, including in subfolders.
2. Assuming you have already followed the [Getting started](../README.md#getting-started) and activated the
   virtual environment, run:

   ```sh
   python scripts/ingest.py
   ```

Chunks are written to the `rag_documents` collection in Qdrant. Ingestion is incremental:

- It only parses and embeds new and changed files, and removes deleted files from the index.
  Re-running with no changes does nothing.
- If a file fails to parse, it's reported and retried on the next run. The other files are still
  ingested.
- `--dry-run` shows what would change without writing anything.
- `--full-rebuild` re-embeds every file.

Each chunk is stored with its source file and page number, so the assistant can cite them. Chunk
size and overlap are set with `RAG_CHUNK_SIZE` and `RAG_CHUNK_OVERLAP`. Changing them only affects
files ingested afterwards, so use `--full-rebuild` to apply them to everything.

The pipeline is in [`src/ingestion/`](../src/ingestion/), with one module per stage: loader,
change detection, parsing, cleaning, chunking and index writing. Each stage can be replaced
independently, e.g. to add a new document source.

## Configuring the RAG assistant

To create a RAG assistant:

1. The search tool in [`tools.py` file](../src/agents/tools.py) searches the Qdrant collections.
2. Modify the amount of documents returned, currently set to 5.
3. Update the `database_search_func` function description to accurately describe what the purpose and contents of your database is.
4. Open [`rag_assistant.py` file](../src/agents/rag_assistant.py) and update the agent's instuctions to describe what the assistant's speciality is and what knowledge it has access to, for example:

   ```python
   instructions = f"""
       You are a helpful HR assistant with the ability to search a database containing information on our company's policies, benefits and handbook.
       Today's date is {current_date}.

       NOTE: THE USER CAN'T SEE THE TOOL RESPONSE.

       A few things to remember:
       - If you have access to multiple databases, gather information from a diverse range of sources before crafting your response.
       - Please include the source of the information used in your response.
       - Use a friendly but professional tone when replying.
       - Only use information from the database. Do not use information from outside sources.
       """
   ```

5. Open [`streamlit_app.py` file](../src/streamlit_app.py) and update the agent's welcome message:

   ```python
   WELCOME = """Hello! I'm your AI-powered HR assistant, here to help you navigate company policies, the employee handbook, and benefits. Ask me anything!""
   ```

6. Run the application and test your RAG assistant.
