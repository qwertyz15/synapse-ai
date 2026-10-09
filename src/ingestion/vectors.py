"""Vector storage on Qdrant.

A Qdrant server (QDRANT_URL) in production; without one, an embedded store in the QDRANT_PATH folder,
which only one process may open (fine for local runs and tests, not for a separate worker).
Collections keep vectors, payload and the HNSW index on disk so memory stays small.
"""

import atexit
import threading
import uuid
from collections.abc import Collection, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient, models

from core import settings
from ingestion.sparse import document_vector, query_vector

# Chunks are embedded and written this many at a time, which bounds memory for large files.
WRITE_BATCH = 128
SCROLL_PAGE = 256
# Payload fields searches and deletes filter on.
INDEXED_FIELDS = ("doc_id", "source", "user_id", "thread_id")
_TEXT, _ID = "page_content", "chunk_id"
# The sparse (keyword) vector next to the unnamed dense one; Qdrant applies IDF to it.
SPARSE = "bm25"
_FUSIONS = {"dbsf": models.Fusion.DBSF, "rrf": models.Fusion.RRF}
# Each side of a hybrid search fetches this many times the results asked for, before fusion.
CANDIDATE_FACTOR = 4
# Collections checked (and, if needed, upgraded) for keyword vectors in this process.
_hybrid_ready: set[tuple[str, str]] = set()

_clients: dict[str, QdrantClient] = {}
_clients_lock = threading.Lock()
# The embedded store isn't safe across threads; a server is.
_embedded_lock = threading.RLock()


def qdrant_client() -> QdrantClient:
    if settings.QDRANT_URL:
        key = settings.QDRANT_URL
    else:
        key = str(Path(settings.QDRANT_PATH).resolve())
    with _clients_lock:
        if key not in _clients:
            if settings.QDRANT_URL:
                api_key = (
                    settings.QDRANT_API_KEY.get_secret_value() if settings.QDRANT_API_KEY else None
                )
                _clients[key] = QdrantClient(url=settings.QDRANT_URL, api_key=api_key)
            else:
                _clients[key] = QdrantClient(path=key)
        return _clients[key]


@atexit.register
def _close_clients() -> None:
    # Closing during interpreter shutdown fails noisily in the embedded store; close first.
    with _clients_lock:
        for client in _clients.values():
            client.close()
        _clients.clear()


def _point_id(chunk_id: str) -> str:
    # Qdrant ids must be UUIDs or integers; derive a stable one from the chunk id.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def _filter(match: dict[str, Any] | None, exclude: dict[str, Collection[str]] | None = None):
    if not match and not exclude:
        return None
    must = [
        models.FieldCondition(key=k, match=models.MatchValue(value=v))
        for k, v in (match or {}).items()
    ]
    must_not = [
        models.FieldCondition(key=k, match=models.MatchAny(any=list(values)))
        for k, values in (exclude or {}).items()
        if values
    ]
    return models.Filter(must=must or None, must_not=must_not or None)


class VectorStore:
    """One Qdrant collection of document chunks; metadata fields are stored flat in the payload."""

    def __init__(self, collection: str, embeddings: Embeddings | None = None):
        self.collection = collection
        self.embeddings = embeddings
        self.client = qdrant_client()

    @contextmanager
    def _guard(self) -> Iterator[None]:
        with nullcontext() if settings.QDRANT_URL else _embedded_lock:
            yield

    def exists(self) -> bool:
        with self._guard():
            return self.client.collection_exists(self.collection)

    def _create(self, size: int, name: str | None = None) -> None:
        name = name or self.collection
        self.client.create_collection(
            name,
            vectors_config=models.VectorParams(
                size=size, distance=models.Distance.COSINE, on_disk=True
            ),
            sparse_vectors_config={
                SPARSE: models.SparseVectorParams(
                    modifier=models.Modifier.IDF, index=models.SparseIndexParams(on_disk=True)
                )
            },
            on_disk_payload=True,
            hnsw_config=models.HnswConfigDiff(on_disk=True),
        )
        for field in INDEXED_FIELDS:
            self.client.create_payload_index(
                name, field, field_schema=models.PayloadSchemaType.KEYWORD
            )

    def _has_sparse(self, name: str) -> bool:
        params = self.client.get_collection(name).config.params
        return SPARSE in (params.sparse_vectors or {})

    def _ready(self) -> bool:
        """Whether the collection exists, upgrading one made before hybrid search on first use."""
        key = (str(id(self.client)), self.collection)
        if not self.client.collection_exists(self.collection):
            return False
        if key not in _hybrid_ready:
            if not self._has_sparse(self.collection):
                self._upgrade()
            _hybrid_ready.add(key)
        return True

    def _upgrade(self) -> None:
        """Rebuild the collection with keyword vectors, keeping its dense vectors (no re-embedding).

        Qdrant can't add a vector type to an existing collection, so points go to a temporary
        collection and back.
        """
        temp = f"{self.collection}__upgrade"
        if self.client.collection_exists(temp):
            self.client.delete_collection(temp)
        size = self.client.get_collection(self.collection).config.params.vectors.size  # type: ignore[union-attr]
        self._create(size, temp)
        self._copy(self.collection, temp)
        self.client.delete_collection(self.collection)
        self._create(size)
        self._copy(temp, self.collection)
        self.client.delete_collection(temp)

    def _copy(self, source: str, target: str) -> None:
        offset = None
        while True:
            points, offset = self.client.scroll(
                source, limit=SCROLL_PAGE, offset=offset, with_payload=True, with_vectors=True
            )
            if points:
                self.client.upsert(
                    target,
                    points=[
                        _point(p.id, _dense(p.vector), p.payload or {})
                        for p in points  # type: ignore[arg-type]
                    ],
                )
            if offset is None:
                return

    def add(self, chunks: list[Document]) -> None:
        if not chunks:
            return
        if self.embeddings is None:
            raise ValueError("Adding chunks needs embeddings")
        for start in range(0, len(chunks), WRITE_BATCH):
            batch = chunks[start : start + WRITE_BATCH]
            self.add_embedded(
                batch, self.embeddings.embed_documents([c.page_content for c in batch])
            )

    def add_embedded(self, chunks: list[Document], vectors: list[list[float]]) -> None:
        """Write chunks whose vectors are already computed, e.g. copied from another store."""
        if not chunks:
            return
        points = [
            _point(_point_id(str(c.id)), list(v), {**c.metadata, _TEXT: c.page_content, _ID: c.id})
            for c, v in zip(chunks, vectors)
        ]
        with self._guard():
            if not self._ready():
                self._create(len(vectors[0]))
                _hybrid_ready.add((str(id(self.client)), self.collection))
            self.client.upsert(self.collection, points=points)

    def count(self, match: dict[str, Any] | None = None) -> int:
        with self._guard():
            if not self.client.collection_exists(self.collection):
                return 0
            return self.client.count(self.collection, count_filter=_filter(match), exact=True).count

    def delete(self, match: dict[str, Any]) -> None:
        with self._guard():
            if self.client.collection_exists(self.collection):
                self.client.delete(
                    self.collection, points_selector=models.FilterSelector(filter=_filter(match))
                )

    def search(
        self,
        query: str,
        k: int = 5,
        match: dict[str, Any] | None = None,
        candidates: int | None = None,
    ) -> list[Document]:
        """The k best chunks for `query`, best first.

        With HYBRID_SEARCH (the default), meaning (dense vectors) and keywords (BM25) are searched
        together and merged by HYBRID_FUSION. `candidates` sets how many each side considers
        (default k * CANDIDATE_FACTOR); a reranker can ask for a larger k and reorder it.
        """
        if self.embeddings is None:
            raise ValueError("Searching needs embeddings")
        with self._guard():
            if not self._ready():
                return []
        vector = self.embeddings.embed_query(query)
        selected = _filter(match)
        indices, values = query_vector(query) if settings.HYBRID_SEARCH else ([], [])
        with self._guard():
            if not indices:
                points = self.client.query_points(
                    self.collection, query=vector, query_filter=selected, limit=k, with_payload=True
                ).points
            else:
                pool = max(candidates or k * CANDIDATE_FACTOR, k)
                points = self.client.query_points(
                    self.collection,
                    prefetch=[
                        models.Prefetch(query=vector, filter=selected, limit=pool),
                        models.Prefetch(
                            query=models.SparseVector(indices=indices, values=values),
                            using=SPARSE,
                            filter=selected,
                            limit=pool,
                        ),
                    ],
                    query=models.FusionQuery(fusion=_FUSIONS[settings.HYBRID_FUSION]),
                    limit=k,
                    with_payload=True,
                ).points
        return [_document(p.payload or {}) for p in points]

    def metadatas(self, match: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Metadata of every matching chunk, read page by page."""
        found: list[dict[str, Any]] = []
        offset = None
        with self._guard():
            if not self.client.collection_exists(self.collection):
                return found
            while True:
                points, offset = self.client.scroll(
                    self.collection,
                    scroll_filter=_filter(match),
                    limit=SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                found += [_document(p.payload or {}).metadata for p in points]
                if offset is None:
                    return found

    def set_fields(
        self,
        match: dict[str, Any],
        values: dict[str, Any],
        exclude: dict[str, Collection[str]] | None = None,
    ) -> int:
        """Overwrite metadata fields on matching chunks; returns how many chunks matched."""
        with self._guard():
            if not self.client.collection_exists(self.collection):
                return 0
            selected = _filter(match, exclude)
            total = self.client.count(self.collection, count_filter=selected, exact=True).count
            if total:
                self.client.set_payload(
                    self.collection, payload=values, points=models.FilterSelector(filter=selected)
                )
            return total

    def reset(self) -> None:
        with self._guard():
            if self.client.collection_exists(self.collection):
                self.client.delete_collection(self.collection)


def _document(payload: dict[str, Any]) -> Document:
    metadata = {k: v for k, v in payload.items() if k not in (_TEXT, _ID)}
    return Document(id=payload.get(_ID), page_content=payload.get(_TEXT, ""), metadata=metadata)


def _point(point_id: Any, dense: list[float], payload: dict[str, Any]) -> models.PointStruct:
    """A chunk with its dense vector and, when its text has any keywords, its BM25 vector."""
    vector: dict[str, Any] = {"": dense}
    indices, values = document_vector(str(payload.get(_TEXT, "")))
    if indices:
        vector[SPARSE] = models.SparseVector(indices=indices, values=values)
    return models.PointStruct(id=point_id, vector=vector, payload=payload)


def _dense(vector: Any) -> list[float]:
    # Points read back come as a plain list (old collections) or a dict of named vectors.
    return list(vector[""] if isinstance(vector, dict) else vector)
