import math
import os
import re

import numexpr
from langchain_core.documents import Document
from langchain_core.tools import BaseTool, tool

from core import settings
from core.embeddings import get_embeddings
from ingestion.index import open_vectorstore


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
    return f"[Source: {citation}]\n{doc.page_content}"


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


def database_search_func(query: str) -> str:
    """Searches chroma_db for information in the company's handbook."""
    # Get the chroma retriever
    retriever = load_chroma_db()

    # Search the database for relevant documents
    documents = retriever.invoke(query)

    # Format the documents into a string
    context_str = format_contexts(documents)

    return context_str


database_search: BaseTool = tool(database_search_func)
database_search.name = "Database_Search"  # Update name with the purpose of your database
