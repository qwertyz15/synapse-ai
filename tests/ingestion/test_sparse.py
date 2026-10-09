"""The BM25 keyword encoder behind hybrid search."""

from ingestion import sparse


def test_tokens_lowercase_and_drop_noise_but_keep_codes_numbers_and_other_scripts():
    assert sparse.tokens("The Invoice INV-4217 is in Section 7 of a file") == [
        "invoice",
        "inv",
        "4217",
        "section",
        "7",
        "file",
    ]
    assert sparse.tokens("ঢাকার আবহাওয়া") == ["ঢাকার", "আবহাওয়া"]


def test_term_ids_are_stable():
    assert sparse.term_id("invoice") == sparse.term_id("invoice") != sparse.term_id("invoices")


def _weights(text):
    ids, values = sparse.document_vector(text)
    return dict(zip(ids, values))


def test_repeated_terms_weigh_more_with_diminishing_returns():
    weights = _weights("zephyr zephyr zephyr budget")
    zephyr, budget = weights[sparse.term_id("zephyr")], weights[sparse.term_id("budget")]
    assert zephyr > budget > 0
    assert zephyr < 3 * budget


def test_the_same_term_counts_less_in_a_longer_chunk():
    short = _weights("budget review")[sparse.term_id("budget")]
    long = _weights("budget " + "filler " * 500)[sparse.term_id("budget")]
    assert long < short


def test_queries_weigh_each_distinct_term_once():
    ids, values = sparse.query_vector("budget budget for zephyr?")
    assert sorted(ids) == sorted([sparse.term_id("budget"), sparse.term_id("zephyr")])
    assert values == [1.0, 1.0]
    assert sparse.query_vector("the and of") == ([], [])
