"""HTTP-level tests against the FastAPI app with a temporary database."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@pytest.fixture
def client(settings, monkeypatch):
    """App wired to the per-test settings, with the embedding model disabled.

    Semantic retrieval is switched off so the HTTP suite runs offline; the
    status endpoint is then expected to *report* it as unavailable, which is
    itself worth asserting.
    """
    monkeypatch.setattr(
        "app.retrieval.embeddings.EmbeddingBackend._load_model",
        lambda self: (_ for _ in ()).throw(
            __import__("app.retrieval.embeddings", fromlist=["EmbeddingUnavailable"])
            .EmbeddingUnavailable("model disabled for tests")
        ),
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_status_reports_unavailable_methods_with_a_reason(client):
    payload = client.get("/api/status").json()
    methods = {item["name"]: item for item in payload["methods"]}

    assert methods["keyword"]["available"] is True
    assert methods["semantic"]["available"] is False
    assert methods["semantic"]["reason"]
    assert methods["hybrid"]["available"] is False
    assert payload["llm_configured"] is False


def test_status_never_exposes_the_api_key(settings, monkeypatch):
    monkeypatch.setattr(
        "app.retrieval.embeddings.EmbeddingBackend._load_model",
        lambda self: (_ for _ in ()).throw(
            __import__("app.retrieval.embeddings", fromlist=["EmbeddingUnavailable"])
            .EmbeddingUnavailable("disabled")
        ),
    )
    settings.llm_base_url = "https://provider.invalid/v1"
    settings.llm_api_key = "sk-super-secret-value"
    settings.llm_model = "test-model"

    with TestClient(create_app(settings)) as client:
        body = client.get("/api/status").text

    assert "sk-super-secret-value" not in body
    assert "provider.invalid" not in body


def test_sample_corpus_load_is_idempotent_over_http(client):
    first = client.post("/api/sample-corpus").json()
    second = client.post("/api/sample-corpus").json()

    assert first["ingested"] == 18
    assert second["ingested"] == 0
    assert second["duplicates"] == 18
    assert second["document_count"] == 18


def test_document_listing_and_detail(client):
    client.post("/api/sample-corpus")

    documents = client.get("/api/documents").json()
    assert len(documents) == 18

    legacy = [d for d in documents if d["doc_id"] == "nd-auth-legacy-006"][0]
    assert legacy["status"] == "superseded"
    assert legacy["superseded_by"] == "nd-auth-005"

    detail = client.get("/api/documents/nd-auth-005").json()
    assert detail["document"]["status"] == "current"
    assert detail["chunks"], "a document should expose its chunks"


def test_missing_document_returns_404(client):
    assert client.get("/api/documents/does-not-exist").status_code == 404


def test_search_returns_chunks_with_provenance(client):
    client.post("/api/sample-corpus")
    response = client.post(
        "/api/search",
        json={"query": "webhook retry schedule", "method": "keyword", "top_k": 3},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["method"] == "keyword"
    assert "BM25" in payload["score_semantics"]
    assert len(payload["results"]) <= 3
    top = payload["results"][0]
    for field in ("chunk_id", "doc_id", "score", "rank", "start_line", "end_line", "filename"):
        assert field in top


def test_search_with_unavailable_method_returns_503(client):
    client.post("/api/sample-corpus")
    response = client.post(
        "/api/search", json={"query": "anything", "method": "semantic", "top_k": 3}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "method_unavailable"


def test_blank_query_is_a_validation_error(client):
    response = client.post("/api/search", json={"query": "   ", "method": "keyword"})
    assert response.status_code == 422


def test_answer_endpoint_returns_evidence_and_citations(client):
    client.post("/api/sample-corpus")
    response = client.post(
        "/api/answer",
        json={
            "question": "How long before an API key expires?",
            "method": "keyword",
            "mode": "extractive",
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["insufficient_evidence"] is False
    assert payload["citations"]
    retrieved = {chunk["chunk_id"] for chunk in payload["retrieval"]["chunks"]}
    assert set(payload["citations"]) <= retrieved
    assert payload["abstention"]["coverage"] >= 0


def test_answer_endpoint_abstains_on_an_out_of_corpus_question(client):
    client.post("/api/sample-corpus")
    response = client.post(
        "/api/answer",
        json={
            "question": "What is the best wine pairing for grilled salmon?",
            "method": "keyword",
            "mode": "extractive",
        },
    )
    payload = response.json()
    assert payload["insufficient_evidence"] is True
    assert payload["citations"] == []


def test_llm_mode_is_refused_when_unconfigured(client):
    client.post("/api/sample-corpus")
    response = client.post(
        "/api/answer",
        json={"question": "anything?", "method": "keyword", "mode": "llm"},
    )
    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]


# --- uploads ----------------------------------------------------------------


def upload(client, name: str, content: bytes):
    return client.post("/api/documents", files={"file": (name, io.BytesIO(content), "text/markdown")})


def test_upload_accepts_a_markdown_file(client):
    body = b"---\nid: uploaded-doc\ntitle: Uploaded\n---\n# Uploaded\n\nSome body text here.\n"
    payload = upload(client, "uploaded.md", body).json()

    assert payload["status"] == "ingested"
    assert payload["doc_id"] == "uploaded-doc"
    assert payload["chunk_count"] >= 1


def test_uploading_identical_content_twice_is_reported_as_duplicate(client):
    body = b"# Repeat\n\nIdentical content uploaded twice over.\n"
    first = upload(client, "one.md", body).json()
    second = upload(client, "two.md", body).json()

    assert first["status"] == "ingested"
    assert second["status"] == "duplicate"
    assert second["doc_id"] == first["doc_id"]


def test_oversized_upload_is_rejected_with_400(client):
    oversized = b"x" * (client.app.state.settings.max_upload_bytes + 1)
    response = upload(client, "big.md", oversized)

    assert response.status_code == 400
    assert response.json()["code"] == "file_too_large"


def test_unsupported_extension_is_rejected_with_400(client):
    response = upload(client, "payload.pdf", b"%PDF-1.4 not really a pdf")
    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_type"


def test_traversal_filename_is_sanitised_not_honoured(client):
    body = b"# Traversal\n\nBody text for the traversal test case.\n"
    payload = upload(client, "../../etc/passwd.md", body).json()

    assert payload["status"] == "ingested"
    assert "/" not in payload["filename"] and ".." not in payload["filename"]


def test_non_utf8_upload_is_rejected_with_400(client):
    response = upload(client, "binary.md", b"\xff\xfe\x00\x01garbage")
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_encoding"


def test_chunk_endpoint_serves_a_citation_target(client):
    client.post("/api/sample-corpus")
    response = client.get("/api/chunks/nd-auth-005::0000")

    assert response.status_code == 200
    payload = response.json()
    assert payload["chunk_id"] == "nd-auth-005::0000"
    assert payload["text"]
    assert payload["start_line"] >= 1


def test_examples_endpoint_covers_the_documented_cases(client):
    examples = client.get("/api/examples").json()["examples"]
    labels = " ".join(item["label"].lower() for item in examples)

    assert "answerable" in labels
    assert "not in the corpus" in labels
    assert "version conflict" in labels
