"""Okapi BM25 over chunk text.

Written out rather than pulled from a library so the ranking is inspectable and
directly unit-testable. The corpus is small enough that a dict-of-postings index
and a linear scan over candidate chunks are comfortably fast.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Deliberately short. An aggressive stopword list hurts this corpus, where
# questions like "what is the default limit" lean on words a long list removes.
STOPWORDS = frozenset(
    """
    a an and are as at be but by for from how if in into is it its of on or
    s t that the their then there these this to was were what when where which
    who why will with does do did can could should would i you we they
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stopwords removed."""
    return [token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS]


class BM25Index:
    """Okapi BM25 with the standard k1/b parameterisation."""

    def __init__(
        self,
        doc_ids: list[str],
        documents: list[str],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if len(doc_ids) != len(documents):
            raise ValueError("doc_ids and documents must be the same length")

        self.k1 = k1
        self.b = b
        self.doc_ids = list(doc_ids)
        self.doc_count = len(doc_ids)

        self.term_frequencies: list[Counter[str]] = []
        self.doc_lengths: list[int] = []
        self.postings: dict[str, list[int]] = defaultdict(list)

        for position, text in enumerate(documents):
            tokens = tokenize(text)
            frequencies = Counter(tokens)
            self.term_frequencies.append(frequencies)
            self.doc_lengths.append(len(tokens))
            for term in frequencies:
                self.postings[term].append(position)

        self.average_length = (
            sum(self.doc_lengths) / self.doc_count if self.doc_count else 0.0
        )

        self.idf: dict[str, float] = {}
        for term, positions in self.postings.items():
            df = len(positions)
            # Probabilistic idf with the +1 guard, so a term in every document
            # scores a small positive value rather than a negative one.
            self.idf[term] = math.log(
                1.0 + (self.doc_count - df + 0.5) / (df + 0.5)
            )

    def score(self, query: str) -> dict[int, float]:
        """Score only the chunks that contain at least one query term."""
        query_terms = tokenize(query)
        if not query_terms or not self.doc_count:
            return {}

        scores: dict[int, float] = defaultdict(float)
        for term in query_terms:
            positions = self.postings.get(term)
            if not positions:
                continue
            idf = self.idf[term]
            for position in positions:
                frequency = self.term_frequencies[position][term]
                length_norm = 1.0 - self.b + self.b * (
                    self.doc_lengths[position] / self.average_length
                    if self.average_length
                    else 0.0
                )
                denominator = frequency + self.k1 * length_norm
                if denominator:
                    scores[position] += idf * (frequency * (self.k1 + 1.0)) / denominator
        return dict(scores)

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """Return ``(chunk_id, score)`` for the top ``top_k`` matches."""
        scores = self.score(query)
        if not scores:
            return []
        ranked = sorted(
            scores.items(),
            # Tie-break on index position so results are deterministic.
            key=lambda item: (-item[1], item[0]),
        )[:top_k]
        return [(self.doc_ids[position], score) for position, score in ranked]
