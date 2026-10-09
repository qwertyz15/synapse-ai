"""BM25 keyword vectors for hybrid search, without a model or extra dependencies.

A chunk becomes a sparse vector of term weights: the BM25 term-frequency part, which depends only on
the chunk. Qdrant applies the IDF part itself (the collection's sparse vector uses Modifier.IDF), so a
term that appears in many chunks counts for less. Words are hashed to ids, so there's no vocabulary
to store, and any language that separates words with spaces or punctuation works.
"""

import unicodedata
import zlib
from collections import Counter
from collections.abc import Iterator

# Standard BM25 parameters; AVG_LENGTH is a typical chunk length in words, as in Qdrant's own BM25.
K1 = 1.2
B = 0.75
AVG_LENGTH = 256

# Very common English words carry no meaning on their own; other languages are left as they are.
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have he her his i if in into is it its me my no not "
    "of on or our she so that the their them then there these they this to was we were what when "
    "where which who will with you your".split()
)


def _keep(word: str) -> bool:
    # Single letters and stopwords say little; single digits can matter ("version 2").
    return word.isdigit() or (len(word) > 1 and word not in _STOPWORDS)


def _words(text: str) -> Iterator[str]:
    # Letters, digits and combining marks: \w alone splits words in scripts such as Bangla or Hindi,
    # whose vowel signs are combining marks.
    word: list[str] = []
    for char in text:
        if char.isalnum() or unicodedata.category(char).startswith("M"):
            word.append(char)
        elif word:
            yield "".join(word)
            word = []
    if word:
        yield "".join(word)


def tokens(text: str) -> list[str]:
    return [w for w in _words(text.lower()) if _keep(w)]


def term_id(term: str) -> int:
    return zlib.crc32(term.encode("utf-8"))


def _ids_and_weights(weights: dict[str, float]) -> tuple[list[int], list[float]]:
    # Two words could hash to the same id; merge them so ids stay unique.
    merged: dict[int, float] = {}
    for term, weight in weights.items():
        merged[term_id(term)] = merged.get(term_id(term), 0.0) + weight
    return list(merged), list(merged.values())


def document_vector(text: str) -> tuple[list[int], list[float]]:
    """(indices, values) for a chunk: each term's BM25 term-frequency weight."""
    words = tokens(text)
    counts = Counter(words)
    norm = K1 * (1 - B + B * len(words) / AVG_LENGTH)
    return _ids_and_weights({t: tf * (K1 + 1) / (tf + norm) for t, tf in counts.items()})


def query_vector(text: str) -> tuple[list[int], list[float]]:
    """(indices, values) for a search: every distinct term counts once; Qdrant adds the IDF."""
    return _ids_and_weights(dict.fromkeys(tokens(text), 1.0))
