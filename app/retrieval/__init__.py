"""Retrieval: BM25 keyword search, embedding search, and RRF hybrid fusion."""

from .bm25 import BM25Index, tokenize
from .embeddings import EmbeddingBackend, EmbeddingUnavailable
from .fusion import reciprocal_rank_fusion
from .service import (
    METHODS,
    SCORE_SEMANTICS,
    MethodStatus,
    RetrievalResult,
    RetrievalService,
    RetrievedChunk,
)

__all__ = [
    "BM25Index",
    "EmbeddingBackend",
    "EmbeddingUnavailable",
    "METHODS",
    "MethodStatus",
    "RetrievalResult",
    "RetrievalService",
    "RetrievedChunk",
    "SCORE_SEMANTICS",
    "reciprocal_rank_fusion",
    "tokenize",
]
