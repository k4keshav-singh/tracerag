"""Semantic retrieval via Sentence Transformers plus NumPy cosine similarity.

No vector database: the corpus is small, so an in-memory float32 matrix and a
single mat-vec product are both simpler and faster than any index would be.
Embeddings are cached on disk keyed by a fingerprint of the corpus and the
embedding configuration, so restarts are cheap and a configuration change
forces a rebuild rather than silently reusing stale vectors.

If the model cannot be loaded - no network on first run, no local cache - this
module reports itself unavailable with the reason. It never substitutes another
method under the semantic name.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger(__name__)

EMBEDDINGS_FILENAME = "embeddings.npy"
EMBEDDINGS_META_FILENAME = "embeddings.meta.json"


class EmbeddingUnavailable(RuntimeError):
    """The embedding model could not be loaded. Carries a human-readable reason."""


def _normalise(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows so cosine similarity is a plain dot product."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Guard against a zero vector producing NaNs.
    norms[norms == 0.0] = 1.0
    return matrix / norms


class EmbeddingBackend:
    """Lazily-loaded Sentence Transformers model with a disk-cached matrix."""

    def __init__(self, model_name: str, index_dir: Path) -> None:
        self.model_name = model_name
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self._model = None
        self._unavailable_reason: str | None = None

        self.chunk_ids: list[str] = []
        self.matrix: np.ndarray | None = None
        self.fingerprint: str | None = None

    # --- model loading -------------------------------------------------

    @property
    def available(self) -> bool:
        """True when the model loaded and a matching embedding matrix is loaded."""
        return self.matrix is not None and self._unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        return self._unavailable_reason

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self._unavailable_reason is not None:
            raise EmbeddingUnavailable(self._unavailable_reason)
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - import-environment specific
            self._unavailable_reason = (
                f"sentence-transformers is not installed ({exc.__class__.__name__}: {exc})."
            )
            raise EmbeddingUnavailable(self._unavailable_reason) from exc

        try:
            self._model = SentenceTransformer(self.model_name)
        except Exception as exc:
            self._unavailable_reason = (
                f"could not load embedding model '{self.model_name}' "
                f"({exc.__class__.__name__}: {exc}). The model is downloaded on "
                "first use and needs network access unless it is already cached."
            )
            raise EmbeddingUnavailable(self._unavailable_reason) from exc
        return self._model

    # --- building and caching -------------------------------------------

    def _cache_paths(self) -> tuple[Path, Path]:
        return (
            self.index_dir / EMBEDDINGS_FILENAME,
            self.index_dir / EMBEDDINGS_META_FILENAME,
        )

    def _load_cache(self, fingerprint: str, chunk_ids: list[str]) -> bool:
        matrix_path, meta_path = self._cache_paths()
        if not matrix_path.exists() or not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if meta.get("fingerprint") != fingerprint:
            return False
        if meta.get("chunk_ids") != chunk_ids:
            return False
        try:
            matrix = np.load(matrix_path)
        except (OSError, ValueError):
            return False
        if matrix.shape[0] != len(chunk_ids):
            return False

        self.matrix = matrix
        self.chunk_ids = list(chunk_ids)
        self.fingerprint = fingerprint
        self._unavailable_reason = None
        return True

    def _write_cache(self, fingerprint: str, chunk_ids: list[str]) -> None:
        matrix_path, meta_path = self._cache_paths()
        np.save(matrix_path, self.matrix)
        meta_path.write_text(
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "model": self.model_name,
                    "chunk_ids": chunk_ids,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def build(
        self, chunk_ids: list[str], texts: list[str], fingerprint: str
    ) -> None:
        """Build or reload the embedding matrix for the given chunks.

        Raises :class:`EmbeddingUnavailable` when the model cannot be loaded;
        callers are expected to treat that as "semantic retrieval is off" rather
        than as a fatal error.
        """
        # Load the model before anything else - before the empty-corpus early
        # return, and before a cache hit. Two reasons: `available` must mean
        # "can actually serve a query", not "has vectors on disk" or "has an
        # empty corpus"; and loading here moves a multi-second cost off the
        # first user query and into start-up, where it belongs.
        model = self._load_model()

        if not chunk_ids:
            self.chunk_ids = []
            self.matrix = np.zeros((0, 1), dtype=np.float32)
            self.fingerprint = fingerprint
            return

        if self._load_cache(fingerprint, chunk_ids):
            LOGGER.info("Reusing cached embeddings for fingerprint %s", fingerprint[:12])
            return

        LOGGER.info("Embedding %d chunks with %s", len(chunk_ids), self.model_name)
        vectors = model.encode(
            texts,
            batch_size=32,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        self.matrix = _normalise(np.asarray(vectors, dtype=np.float32))
        self.chunk_ids = list(chunk_ids)
        self.fingerprint = fingerprint
        self._unavailable_reason = None
        self._write_cache(fingerprint, chunk_ids)

    # --- querying --------------------------------------------------------

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """Cosine similarity between the query and every chunk.

        Scores are in [-1, 1] and are *not* comparable with BM25 scores.
        """
        if self.matrix is None or not self.chunk_ids:
            raise EmbeddingUnavailable(
                self._unavailable_reason or "embeddings have not been built"
            )
        model = self._load_model()
        query_vector = model.encode(
            [query], convert_to_numpy=True, show_progress_bar=False
        )
        query_vector = _normalise(np.asarray(query_vector, dtype=np.float32))[0]

        similarities = self.matrix @ query_vector
        if top_k >= len(similarities):
            order = np.argsort(-similarities, kind="stable")
        else:
            # argpartition for the top_k, then sort just that slice.
            partitioned = np.argpartition(-similarities, top_k)[:top_k]
            order = partitioned[np.argsort(-similarities[partitioned], kind="stable")]

        return [(self.chunk_ids[int(i)], float(similarities[int(i)])) for i in order[:top_k]]
