"""Shared fixtures.

Tests run against a temporary database and a small purpose-built corpus unless
they explicitly ask for the real sample corpus. Nothing here touches the
developer's working ``data/tracerag.db``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.ingest import load_sample_corpus
from app.retrieval import RetrievalService

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed at a throwaway data directory."""
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        corpus_dir=REPO_ROOT / "data" / "corpus",
        index_dir=tmp_path / "index",
        chunk_size=600,
        chunk_overlap=120,
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
    )


@pytest.fixture
def db(settings: Settings) -> Database:
    return Database(settings.db_path)


@pytest.fixture
def sample_corpus(db: Database, settings: Settings) -> Database:
    load_sample_corpus(db, settings)
    return db


@pytest.fixture
def keyword_service(sample_corpus: Database, settings: Settings) -> RetrievalService:
    """A service whose index is built, with semantic retrieval forced off.

    Keeping the embedding model out of the default test path means the suite
    runs offline and in seconds. The tests that genuinely need embeddings are
    marked and skip when the model is unavailable.
    """
    service = RetrievalService(sample_corpus, settings)
    service.embeddings._unavailable_reason = "disabled for this test"
    service.rebuild()
    service._semantic_reason = "disabled for this test"
    return service


@pytest.fixture
def adversarial_text() -> str:
    return (FIXTURES / "adversarial_doc.md").read_text(encoding="utf-8")
