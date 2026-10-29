"""Runtime configuration.

Everything here is read from the environment (or a local .env file) so the same
image can run with or without an LLM provider configured. Secrets never leave
the server: the browser only ever sees whether LLM mode is *available*, never
the key itself.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- storage -------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    db_path: Path = REPO_ROOT / "data" / "tracerag.db"
    corpus_dir: Path = REPO_ROOT / "data" / "corpus"
    index_dir: Path = REPO_ROOT / "data" / "index"

    # --- ingestion -----------------------------------------------------
    # Chunk size is measured in characters, not tokens. Characters are the unit
    # the chunker actually controls, and reporting the unit we control keeps the
    # configuration honest. ~900 chars is roughly 200-230 English tokens.
    chunk_size: int = 900
    chunk_overlap: int = 180
    max_upload_bytes: int = 1_048_576  # 1 MiB, per spec

    # --- retrieval -----------------------------------------------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rrf_k: int = 60
    default_top_k: int = 5
    max_top_k: int = 20

    # --- abstention ----------------------------------------------------
    # Fraction of the question's content terms that must appear somewhere in the
    # retrieved evidence before TraceRAG is willing to answer.
    #
    # 0.55 comes from a sweep over the 20 development questions only, with
    # hybrid retrieval (`python -m app.evaluate --split dev --calibrate`). At
    # 0.55 the dev split refuses 3/3 unanswerable questions while wrongly
    # refusing 1/17 answerable ones (balanced accuracy 0.97); the next step
    # down, 0.50, catches only 1 of the 3. Nothing was tuned against the
    # held-out test split. This is calibrated for this corpus, not a universal
    # threshold - see docs/design-decisions.md.
    abstain_coverage_threshold: float = 0.55
    abstain_evidence_chunks: int = 5

    # --- optional LLM provider -----------------------------------------
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 30.0

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
