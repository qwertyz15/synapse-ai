# Creating a RAG assistant

You can build a RAG assistant using a Chroma database.

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

1. Put your documents in `./data` (or set `RAG_DATA_DIR`). PDF, Word (`.docx`), text (`.txt`) and
   Markdown (`.md`) files are supported, including in subfolders.
2. Assuming you have already followed the [Quickstart](../README.md#quickstart) and activated the
   virtual environment, run:

   ```sh
   python scripts/ingest.py
   ```

The database is written to `./chroma_db` (or `CHROMA_DB_PATH`). Ingestion is incremental:

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

1. The search tool in [`tools.py` file](../src/agents/tools.py) reads the database at `CHROMA_DB_PATH`.
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
