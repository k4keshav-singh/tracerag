"""The retrieval service: one index, three methods, one result shape.

`keyword` and `semantic` are the base methods; `hybrid` fuses their rankings
with reciprocal rank fusion. Every method returns the same
:class:`RetrievedChunk` shape so callers - the API, the evaluator, the answerer -
never branch on which method produced a result.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field

from ..config import Settings
from ..db import Database
from .bm25 import BM25Index, tokenize
from .embeddings import EmbeddingBackend, EmbeddingUnavailable
from .fusion import reciprocal_rank_fusion

LOGGER = logging.getLogger(__name__)

METHODS = ("keyword", "semantic", "hybrid")

# How each method's score should be read. Surfaced through the API so the UI can
# say so rather than implying the numbers are interchangeable.
SCORE_SEMANTICS = {
    "keyword": "Okapi BM25 relevance score. Unbounded above; higher is better. "
    "Comparable only between results of the same query.",
    "semantic": "Cosine similarity in [-1, 1] between query and chunk embeddings. "
    "Higher is better.",
    "hybrid": "Reciprocal rank fusion score, the sum of 1/(k+rank) over the "
    "keyword and semantic rankings. Small by construction; it measures "
    "rank agreement, not relevance magnitude.",
}


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    score: float
    rank: int
    text: str
    heading: str
    start_line: int
    end_line: int
    doc_title: str
    filename: str
    doc_status: str | None = None
    doc_version: str | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "score": round(self.score, 6),
            "rank": self.rank,
            "text": self.text,
            "heading": self.heading,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "doc_title": self.doc_title,
            "filename": self.filename,
            "doc_status": self.doc_status,
            "doc_version": self.doc_version,
            "superseded_by": self.superseded_by,
        }


@dataclass
class RetrievalResult:
    method: str
    query: str
    results: list[RetrievedChunk]
    elapsed_ms: float
    score_semantics: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class MethodStatus:
    name: str
    available: bool
    reason: str | None = None


class RetrievalService:
    """Owns the in-memory indexes and keeps them in step with the database."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.embeddings = EmbeddingBackend(
            settings.embedding_model, settings.index_dir
        )

        self._bm25: BM25Index | None = None
        self._chunk_ids: list[str] = []
        self._chunk_lookup: dict[str, dict] = {}
        self._fingerprint: str | None = None
        self._semantic_reason: str | None = "index has not been built yet"

    # --- index lifecycle -------------------------------------------------

    def compute_fingerprint(self) -> str:
        """Fingerprint covering corpus content *and* index-affecting settings.

        Any change here means the stored embeddings no longer describe the
        current chunks, so the index must be rebuilt.
        """
        hasher = hashlib.sha256()
        for doc_id, digest in sorted(self.db.document_hashes().items()):
            hasher.update(doc_id.encode("utf-8"))
            hasher.update(digest.encode("utf-8"))
        hasher.update(f"chunk_size={self.settings.chunk_size}".encode("utf-8"))
        hasher.update(f"chunk_overlap={self.settings.chunk_overlap}".encode("utf-8"))
        hasher.update(f"model={self.settings.embedding_model}".encode("utf-8"))
        return hasher.hexdigest()

    @property
    def corpus_fingerprint(self) -> str | None:
        return self._fingerprint

    def ensure_index(self, *, force: bool = False) -> bool:
        """Rebuild the indexes if the fingerprint moved. Returns True if rebuilt."""
        fingerprint = self.compute_fingerprint()
        if not force and fingerprint == self._fingerprint and self._bm25 is not None:
            return False
        self.rebuild(fingerprint)
        return True

    def rebuild(self, fingerprint: str | None = None) -> None:
        fingerprint = fingerprint or self.compute_fingerprint()
        chunks = self.db.list_chunks()
        documents = {doc.doc_id: doc for doc in self.db.list_documents()}

        self._chunk_ids = [chunk.chunk_id for chunk in chunks]
        texts: list[str] = []
        self._chunk_lookup = {}

        for chunk in chunks:
            document = documents.get(chunk.doc_id)
            # Prepend the title and heading so lexical matching can use them.
            # The stored passage text itself is unchanged.
            indexed_text = "\n".join(
                part
                for part in (
                    document.title if document else "",
                    chunk.heading,
                    chunk.text,
                )
                if part
            )
            texts.append(indexed_text)
            self._chunk_lookup[chunk.chunk_id] = {
                "chunk": chunk,
                "document": document,
            }

        self._bm25 = BM25Index(self._chunk_ids, texts)

        try:
            self.embeddings.build(self._chunk_ids, texts, fingerprint)
            self._semantic_reason = None
        except EmbeddingUnavailable as exc:
            self._semantic_reason = str(exc)
            LOGGER.warning("Semantic retrieval unavailable: %s", exc)

        self._fingerprint = fingerprint
        self.db.set_meta("corpus_fingerprint", fingerprint)
        self.db.set_meta("embedding_model", self.settings.embedding_model)

    # --- status ----------------------------------------------------------

    def method_status(self) -> dict[str, MethodStatus]:
        semantic_ok = self.embeddings.available and self._semantic_reason is None
        reason = self._semantic_reason or self.embeddings.unavailable_reason
        return {
            "keyword": MethodStatus("keyword", True),
            "semantic": MethodStatus("semantic", semantic_ok, None if semantic_ok else reason),
            "hybrid": MethodStatus(
                "hybrid",
                semantic_ok,
                None
                if semantic_ok
                else f"hybrid needs semantic retrieval, which is unavailable: {reason}",
            ),
        }

    def available_methods(self) -> list[str]:
        return [name for name, status in self.method_status().items() if status.available]

    # --- search -----------------------------------------------------------

    def _hydrate(self, scored: list[tuple[str, float]]) -> list[RetrievedChunk]:
        hydrated: list[RetrievedChunk] = []
        for rank, (chunk_id, score) in enumerate(scored, start=1):
            entry = self._chunk_lookup.get(chunk_id)
            if entry is None:
                continue
            chunk = entry["chunk"]
            document = entry["document"]
            hydrated.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    score=score,
                    rank=rank,
                    text=chunk.text,
                    heading=chunk.heading,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    doc_title=document.title if document else chunk.doc_id,
                    filename=document.filename if document else "",
                    doc_status=document.status if document else None,
                    doc_version=document.version if document else None,
                    superseded_by=document.superseded_by if document else None,
                )
            )
        return hydrated

    def search(self, query: str, method: str, top_k: int) -> RetrievalResult:
        if method not in METHODS:
            raise ValueError(f"Unknown retrieval method '{method}'.")
        if not query.strip():
            raise ValueError("Query must not be empty.")

        top_k = max(1, min(top_k, self.settings.max_top_k))
        self.ensure_index()

        status = self.method_status()[method]
        if not status.available:
            raise EmbeddingUnavailable(status.reason or f"{method} is unavailable")

        warnings: list[str] = []
        start = time.perf_counter()

        if method == "keyword":
            scored = self._bm25.search(query, top_k) if self._bm25 else []
        elif method == "semantic":
            scored = self.embeddings.search(query, top_k)
        else:
            # Fuse deeper lists than requested: RRF can promote an item that is
            # mid-ranked in both inputs, which a top_k-sized input would hide.
            depth = min(max(top_k * 4, 20), max(len(self._chunk_ids), 1))
            keyword_ids = [cid for cid, _ in (self._bm25.search(query, depth) if self._bm25 else [])]
            semantic_ids = [cid for cid, _ in self.embeddings.search(query, depth)]
            scored = reciprocal_rank_fusion(
                [keyword_ids, semantic_ids], k=self.settings.rrf_k, top_k=top_k
            )
            if not keyword_ids:
                warnings.append(
                    "No chunk contained any query term; hybrid fell back to the "
                    "semantic ranking alone."
                )

        elapsed_ms = (time.perf_counter() - start) * 1000.0

        if not scored:
            warnings.append("No chunk matched this query.")

        return RetrievalResult(
            method=method,
            query=query,
            results=self._hydrate(scored),
            elapsed_ms=elapsed_ms,
            score_semantics=SCORE_SEMANTICS[method],
            warnings=warnings,
        )

    # --- helpers used by answering and evaluation ------------------------

    @staticmethod
    def query_content_terms(query: str) -> list[str]:
        """Content-bearing query terms used by the abstention heuristic."""
        return [term for term in dict.fromkeys(tokenize(query)) if len(term) >= 3]
