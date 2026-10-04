"""Upload and manage the documents the rag-assistant searches."""

import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from client import AgentClient, AgentClientError
from schema import IngestionResult

SUPPORTED_TYPES = ["pdf", "docx", "txt", "md"]

st.set_page_config(page_title="Documents", page_icon="📄")


def get_client() -> AgentClient:
    # Shared with the chat page through session state when it connected first.
    if "agent_client" not in st.session_state:
        load_dotenv()
        agent_url = os.getenv("AGENT_URL")
        if not agent_url:
            agent_url = f"http://{os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', 8080)}"
        try:
            with st.spinner("Connecting to agent service..."):
                st.session_state.agent_client = AgentClient(base_url=agent_url)
        except AgentClientError as e:
            st.error(f"Error connecting to agent service at {agent_url}: {e}")
            st.stop()
    return st.session_state.agent_client


def show_result(result: IngestionResult) -> None:
    for doc_id in result.new:
        st.success(f"Added **{doc_id}**")
    for doc_id in result.updated:
        st.success(f"Updated **{doc_id}**")
    for doc_id in result.deleted:
        st.info(f"Removed **{doc_id}**")
    for doc_id, error in result.failed.items():
        st.error(f"Couldn't read **{doc_id}**: {error}")
    for name, reason in result.rejected.items():
        st.warning(f"Skipped **{name}**: {reason}")
    if result.full_rebuild:
        st.info("All documents were re-indexed (first run or embedding model changed).")


def format_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return iso


client = get_client()

st.title("📄 Documents")
st.caption(
    "Documents uploaded here are searched by the **research-assistant** (alongside web search) "
    "and **rag-assistant** (documents only) agents. "
    "Uploading a file with an existing name replaces it."
)

# Results are stored across the rerun that refreshes the list and clears the uploader.
if result := st.session_state.pop("rag_last_result", None):
    show_result(result)

st.session_state.setdefault("rag_uploader_key", 0)
uploads = st.file_uploader(
    "Upload documents",
    type=SUPPORTED_TYPES,
    accept_multiple_files=True,
    key=f"rag_uploader_{st.session_state.rag_uploader_key}",
)
if st.button("Upload and index", type="primary", disabled=not uploads):
    with st.spinner("Indexing... embedding large documents can take a minute."):
        try:
            result = client.upload_documents([(f.name, f.getvalue()) for f in uploads])
        except AgentClientError as e:
            st.error(f"Upload failed: {e}")
            st.stop()
    st.session_state.rag_last_result = result
    st.session_state.rag_uploader_key += 1
    st.rerun()

st.subheader("Indexed documents")
try:
    documents = client.list_documents().documents
except AgentClientError as e:
    st.error(f"Couldn't load documents: {e}")
    st.stop()

if not documents:
    st.info("No documents yet. Upload a PDF, Word, text or Markdown file to get started.")

for doc in documents:
    name_col, info_col, delete_col = st.columns([5, 4, 1], vertical_alignment="center")
    name_col.markdown(f"**{doc.doc_id}**")
    info_col.caption(
        f"{doc.file_type.upper()} · {doc.chunk_count} chunks · {format_time(doc.ingested_at)}"
    )
    with delete_col.popover(
        "", icon=":material/delete:", help=f"Delete {doc.doc_id}", key=f"popover_{doc.doc_id}"
    ):
        st.write(f"Delete **{doc.doc_id}**? This removes the file and its search index entries.")
        if st.button("Delete", key=f"delete_{doc.doc_id}", type="primary"):
            with st.spinner("Deleting..."):
                try:
                    st.session_state.rag_last_result = client.delete_document(doc.doc_id)
                except AgentClientError as e:
                    st.error(f"Delete failed: {e}")
                    st.stop()
            st.rerun()
