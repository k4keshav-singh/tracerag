"""BM25 behaviour, RRF correctness, and retrieval of known corpus facts."""

from __future__ import annotations

import pytest

from app.retrieval import BM25Index, RetrievalService, reciprocal_rank_fusion, tokenize
from app.retrieval.embeddings import EmbeddingUnavailable


# --- reciprocal rank fusion -------------------------------------------------


def test_rrf_scores_match_the_formula():
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60)
    scores = dict(fused)
    # Both appear once at rank 1 and once at rank 2.
    expected = 1 / 61 + 1 / 62
    assert scores["a"] == pytest.approx(expected)
    assert scores["b"] == pytest.approx(expected)


def test_rrf_rewards_agreement_across_lists():
    # "shared" is 2nd in both lists; "only_a" is 1st in one and absent from the other.
    fused = reciprocal_rank_fusion([["only_a", "shared"], ["only_b", "shared"]], k=60)
    ranking = [item_id for item_id, _ in fused]
    assert ranking[0] == "shared", "an item ranked by both lists should win"


def test_rrf_handles_an_empty_list():
    fused = reciprocal_rank_fusion([[], ["a", "b"]], k=60)
    assert [item_id for item_id, _ in fused] == ["a", "b"]


def test_rrf_is_deterministic_for_tied_scores():
    first = reciprocal_rank_fusion([["x", "y"], ["y", "x"]], k=60)
    second = reciprocal_rank_fusion([["x", "y"], ["y", "x"]], k=60)
    assert first == second


def test_rrf_respects_top_k():
    fused = reciprocal_rank_fusion([["a", "b", "c", "d"]], k=60, top_k=2)
    assert len(fused) == 2


def test_rrf_rejects_non_positive_k():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)


# --- BM25 -------------------------------------------------------------------


def test_tokenize_drops_stopwords_and_splits_punctuation():
    assert tokenize("The X-RateLimit-Limit is 600!") == ["x", "ratelimit", "limit", "600"]


def test_bm25_ranks_the_matching_document_first():
    index = BM25Index(
        ["doc-a", "doc-b", "doc-c"],
        [
            "The webhook retry schedule uses exponential backoff",
            "API keys expire after ninety days by default",
            "Workspaces contain spaces and desks",
        ],
    )
    results = index.search("webhook retry backoff", top_k=3)
    assert results[0][0] == "doc-a"


def test_bm25_returns_nothing_for_an_unmatched_query():
    index = BM25Index(["doc-a"], ["webhook retry schedule"])
    assert index.search("photosynthesis chlorophyll", top_k=5) == []


def test_bm25_rejects_mismatched_input_lengths():
    with pytest.raises(ValueError):
        BM25Index(["a", "b"], ["only one document"])


def test_bm25_handles_an_empty_index():
    assert BM25Index([], []).search("anything", top_k=5) == []


# --- known facts from the real corpus ---------------------------------------


@pytest.mark.parametrize(
    "query,expected_doc_id",
    [
        ("How long before an API key expires?", "nd-auth-005"),
        ("default sustained rate limit per workspace", "nd-ratelimits-007"),
        ("webhook retry schedule and backoff", "nd-webhook-retries-010"),
        ("maximum page size for list endpoints", "nd-pagination-008"),
        ("how long are audit log entries retained", "nd-retention-011"),
        ("which PostgreSQL version is required", "nd-install-001"),
        ("lowest role that can create an API key", "nd-roles-004"),
    ],
)
def test_keyword_retrieval_finds_known_facts(keyword_service, query, expected_doc_id):
    result = keyword_service.search(query, "keyword", top_k=5)
    retrieved = {chunk.doc_id for chunk in result.results}
    assert expected_doc_id in retrieved, (
        f"expected {expected_doc_id} in top 5 for {query!r}, got {sorted(retrieved)}"
    )


def test_results_carry_source_metadata(keyword_service):
    result = keyword_service.search("webhook retry schedule", "keyword", top_k=3)
    chunk = result.results[0]
    assert chunk.filename.endswith(".md")
    assert chunk.start_line >= 1
    assert chunk.end_line >= chunk.start_line
    assert chunk.doc_title
    assert chunk.rank == 1


def test_superseded_document_metadata_is_exposed(keyword_service):
    result = keyword_service.search(
        "workspace tokens X-Nimbus-Token header", "keyword", top_k=10
    )
    legacy = [c for c in result.results if c.doc_id == "nd-auth-legacy-006"]
    assert legacy, "the superseded legacy auth page should be retrievable"
    assert legacy[0].doc_status == "superseded"
    assert legacy[0].superseded_by == "nd-auth-005"


def test_score_semantics_are_reported_per_method(keyword_service):
    result = keyword_service.search("rate limit", "keyword", top_k=3)
    assert "BM25" in result.score_semantics


def test_unknown_method_is_rejected(keyword_service):
    with pytest.raises(ValueError):
        keyword_service.search("anything", "telepathy", top_k=3)


def test_blank_query_is_rejected(keyword_service):
    with pytest.raises(ValueError):
        keyword_service.search("   ", "keyword", top_k=3)


def test_unavailable_semantic_method_raises_rather_than_substituting(keyword_service):
    """The critical honesty property: no silent fallback under another name."""
    status = keyword_service.method_status()
    assert status["semantic"].available is False
    assert status["hybrid"].available is False

    with pytest.raises(EmbeddingUnavailable):
        keyword_service.search("anything", "semantic", top_k=3)
    with pytest.raises(EmbeddingUnavailable):
        keyword_service.search("anything", "hybrid", top_k=3)

    assert keyword_service.available_methods() == ["keyword"]


def test_index_rebuilds_when_the_corpus_changes(keyword_service, settings):
    from app.ingest import ingest_text

    before = keyword_service.compute_fingerprint()
    ingest_text(
        keyword_service.db,
        settings,
        raw_text="---\nid: brand-new\ntitle: New\n---\n# New\n\nA new body of text.\n",
        filename="new.md",
    )
    after = keyword_service.compute_fingerprint()

    assert after != before, "adding a document must move the fingerprint"
    assert keyword_service.ensure_index() is True, "a moved fingerprint must rebuild"
    assert keyword_service.ensure_index() is False, "a stable fingerprint must not"


def test_fingerprint_tracks_chunking_configuration(keyword_service, settings):
    before = keyword_service.compute_fingerprint()
    settings.chunk_size += 100
    assert keyword_service.compute_fingerprint() != before


def test_fingerprint_tracks_embedding_model(keyword_service, settings):
    before = keyword_service.compute_fingerprint()
    settings.embedding_model = "some/other-model"
    assert keyword_service.compute_fingerprint() != before


# --- semantic and hybrid, when the model is available -----------------------


@pytest.fixture
def full_service(sample_corpus, settings) -> RetrievalService:
    service = RetrievalService(sample_corpus, settings)
    service.ensure_index(force=True)
    if not service.method_status()["semantic"].available:
        pytest.skip("embedding model unavailable in this environment")
    return service


@pytest.mark.slow
def test_semantic_retrieval_handles_a_paraphrase(full_service):
    """A question that shares almost no vocabulary with the source sentence."""
    result = full_service.search(
        "what is the biggest number of records one listing call will hand back",
        "semantic",
        top_k=5,
    )
    assert "nd-pagination-008" in {chunk.doc_id for chunk in result.results}


@pytest.mark.slow
def test_hybrid_fuses_both_rankings(full_service):
    query = "how long until an API key stops working"
    top_k = 10

    # Hybrid deliberately fuses deeper lists than it returns, so that RRF can
    # promote a chunk that is mid-ranked in *both* inputs. Compare against that
    # same depth, not against the top_k-sized lists.
    depth = min(max(top_k * 4, 20), len(full_service._chunk_ids))
    keyword_ids = [c.chunk_id for c in full_service.search(query, "keyword", depth).results]
    semantic_ids = [c.chunk_id for c in full_service.search(query, "semantic", depth).results]
    hybrid_ids = [c.chunk_id for c in full_service.search(query, "hybrid", top_k).results]

    assert hybrid_ids, "hybrid should return results"
    assert set(hybrid_ids) <= set(keyword_ids) | set(semantic_ids), (
        "hybrid must only return chunks that one of its inputs surfaced"
    )
    assert len(hybrid_ids) == top_k, "hybrid should still honour the requested top_k"


@pytest.mark.slow
def test_semantic_scores_are_within_cosine_range(full_service):
    result = full_service.search("rate limits", "semantic", top_k=5)
    for chunk in result.results:
        assert -1.0 <= chunk.score <= 1.0
