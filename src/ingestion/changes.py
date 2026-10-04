from collections.abc import Iterable

from ingestion.models import ChangeSet, SourceDocument


def detect_changes(documents: Iterable[SourceDocument], indexed: dict[str, str]) -> ChangeSet:
    """Compare current documents with the indexed doc_id -> content_hash map."""
    changes = ChangeSet()
    seen: set[str] = set()
    for doc in documents:
        seen.add(doc.doc_id)
        previous_hash = indexed.get(doc.doc_id)
        if previous_hash is None:
            changes.new.append(doc)
        elif previous_hash != doc.content_hash:
            changes.updated.append(doc)
        else:
            changes.unchanged.append(doc)
    changes.deleted = sorted(set(indexed) - seen)
    return changes
