import math
import os
import re

import numexpr
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from core import settings
from core.embeddings import get_embeddings
from ingestion.attachments import open_attachment_store, search_attachments
from ingestion.index import open_vectorstore
from ingestion.user_library import open_user_library, search_user_library


def calculator_func(expression: str) -> str:
    """Calculates a math expression using numexpr.

    Useful for when you need to answer questions about math using numexpr.
    This tool is only for math questions and nothing else. Only input
    math expressions.

    Args:
        expression (str): A valid numexpr formatted math expression.

    Returns:
        str: The result of the math expression.
    """

    try:
        local_dict = {"pi": math.pi, "e": math.e}
        output = str(
            numexpr.evaluate(
                expression.strip(),
                global_dict={},  # restrict access to globals
                local_dict=local_dict,  # add common mathematical functions
            )
        )
        return re.sub(r"^\[|\]$", "", output)
    except Exception as e:
        raise ValueError(
            f'calculator("{expression}") raised error: {e}.'
            " Please try again with a valid numerical expression"
        )


calculator: BaseTool = tool(calculator_func)
calculator.name = "Calculator"


def format_context(doc: Document) -> str:
    source = doc.metadata.get("source", "unknown")
    page = doc.metadata.get("page")
    citation = f"{source}, page {page}" if page is not None else source
    origin = " (attached to this chat)" if doc.metadata.get("scope") == "chat" else ""
    return f"[Source: {citation}]{origin}\n{doc.page_content}"


# Format retrieved documents
def format_contexts(docs):
    return "\n\n".join(format_context(doc) for doc in docs)


def load_chroma_db():
    # Chroma silently creates an empty database at a missing path (e.g. a wrong working directory).
    if not os.path.isdir(settings.CHROMA_DB_PATH):
        raise FileNotFoundError(
            f"No RAG database at {os.path.abspath(settings.CHROMA_DB_PATH)}. "
            "Run scripts/ingest.py to create it."
        )
    chroma_db = open_vectorstore(settings.CHROMA_DB_PATH, get_embeddings())
    retriever = chroma_db.as_retriever(search_kwargs={"k": 5})
    return retriever


def _chat_documents(query: str, config: RunnableConfig | None) -> list[Document]:
    configurable = (config or {}).get("configurable", {})
    thread_id, user_id = configurable.get("thread_id"), configurable.get("user_id")
    if not thread_id or not user_id or not os.path.isdir(settings.CHROMA_DB_PATH):
        return []
    store = open_attachment_store(settings.CHROMA_DB_PATH, get_embeddings())
    return search_attachments(store, query, thread_id, user_id)


def _user_library_documents(query: str, config: RunnableConfig | None) -> list[Document]:
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id or not os.path.isdir(settings.CHROMA_DB_PATH):
        return []
    store = open_user_library(settings.CHROMA_DB_PATH, get_embeddings())
    return search_user_library(store, query, user_id)


def database_search_func(query: str, config: RunnableConfig) -> str:
    """Searches the documents the user has uploaded (PDF, Word, text, Markdown).

    Covers files attached to this chat, the user's own library and the shared document library.
    Use for questions about the user's own files, organization, policies or projects.
    Returns the most relevant passages, each labeled with its source file and page.
    """
    documents = _chat_documents(query, config) + _user_library_documents(query, config)
    try:
        documents += load_chroma_db().invoke(query)
    except FileNotFoundError:
        if not documents:
            raise
    if not documents:
        return "No matching passages found in the uploaded documents."

    # Format the documents into a string
    context_str = format_contexts(documents)

    return context_str


database_search: BaseTool = tool(database_search_func)
database_search.name = "DocumentSearch"  # Update name with the purpose of your database
