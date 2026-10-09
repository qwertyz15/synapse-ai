import math
import re

import numexpr
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

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


def _library_documents(query: str) -> list[Document]:
    return open_vectorstore(get_embeddings()).search(query, 5)


def _chat_documents(query: str, config: RunnableConfig | None) -> list[Document]:
    configurable = (config or {}).get("configurable", {})
    thread_id, user_id = configurable.get("thread_id"), configurable.get("user_id")
    if not thread_id or not user_id:
        return []
    return search_attachments(open_attachment_store(get_embeddings()), query, thread_id, user_id)


def _user_library_documents(query: str, config: RunnableConfig | None) -> list[Document]:
    user_id = (config or {}).get("configurable", {}).get("user_id")
    if not user_id:
        return []
    return search_user_library(open_user_library(get_embeddings()), query, user_id)


def database_search_func(query: str, config: RunnableConfig) -> str:
    """Searches the documents the user has uploaded (PDF, Word, text, Markdown).

    Covers files attached to this chat, the user's own library and the shared document library.
    Use for questions about the user's own files, organization, policies or projects.
    Returns the most relevant passages, each labeled with its source file and page.
    """
    documents = (
        _chat_documents(query, config)
        + _user_library_documents(query, config)
        + _library_documents(query)
    )
    if not documents:
        return "No matching passages found in the uploaded documents."
    return format_contexts(documents)


database_search: BaseTool = tool(database_search_func)
database_search.name = "DocumentSearch"  # Update name with the purpose of your database
