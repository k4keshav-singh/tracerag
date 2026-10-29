"""Evidence selection and the abstention heuristic.

Both answer modes share this module, so "do we have enough to answer?" is
decided the same way whether or not an LLM is configured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..retrieval import RetrievedChunk
from ..retrieval.bm25 import tokenize

# Split on sentence punctuation followed by whitespace, and on line breaks, so
# that markdown bullets and table rows come out as their own units.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class AbstentionDecision:
    """Why TraceRAG did or did not consider the evidence sufficient."""

    insufficient: bool
    coverage: float
    threshold: float
    matched_terms: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "insufficient_evidence": self.insufficient,
            "coverage": round(self.coverage, 4),
            "threshold": self.threshold,
            "matched_terms": self.matched_terms,
            "missing_terms": self.missing_terms,
            "query_terms": self.query_terms,
            "reason": self.reason,
            "heuristic": (
                "Content-term coverage: the fraction of the question's "
                "content-bearing terms (length >= 3, stopwords removed) that "
                "appear in the top retrieved passages. Chosen over a raw "
                "similarity cut-off because one threshold then works across "
                "BM25, cosine and RRF, whose scores are on unrelated scales. "
                "The threshold is calibrated on the 20 development questions "
                "only."
            ),
        }


def content_terms(query: str) -> list[str]:
    """Deduplicated, order-preserving content terms from the question."""
    return [term for term in dict.fromkeys(tokenize(query)) if len(term) >= 3]


def assess_evidence(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    threshold: float,
    evidence_chunks: int,
) -> AbstentionDecision:
    """Decide whether the retrieved passages support answering at all.

    The signal is lexical coverage of the question's content terms within the
    top passages. It is intentionally simple and inspectable: the UI and the
    benchmark both show which terms were and were not found.

    This is a *retrieval-support* check, not a factual-correctness check. It can
    be satisfied by passages that mention every term while answering a different
    question.
    """
    terms = content_terms(query)
    considered = chunks[:evidence_chunks]

    if not considered:
        return AbstentionDecision(
            insufficient=True,
            coverage=0.0,
            threshold=threshold,
            query_terms=terms,
            missing_terms=terms,
            reason="No passages were retrieved for this question.",
        )

    if not terms:
        # Nothing content-bearing to check. Defer rather than claim support.
        return AbstentionDecision(
            insufficient=True,
            coverage=0.0,
            threshold=threshold,
            query_terms=[],
            reason="The question contains no content-bearing terms to match on.",
        )

    evidence_tokens = set()
    for chunk in considered:
        evidence_tokens.update(tokenize(chunk.text))
        evidence_tokens.update(tokenize(chunk.heading))
        evidence_tokens.update(tokenize(chunk.doc_title))

    matched = [term for term in terms if term in evidence_tokens]
    missing = [term for term in terms if term not in evidence_tokens]
    coverage = len(matched) / len(terms)
    insufficient = coverage < threshold

    if insufficient:
        reason = (
            f"Only {len(matched)} of {len(terms)} content terms from the question "
            f"appear in the top {len(considered)} passages "
            f"(coverage {coverage:.2f} < threshold {threshold:.2f}). "
            f"Not found: {', '.join(missing)}."
        )
    else:
        reason = (
            f"{len(matched)} of {len(terms)} content terms from the question appear "
            f"in the top {len(considered)} passages (coverage {coverage:.2f} >= "
            f"threshold {threshold:.2f})."
        )

    return AbstentionDecision(
        insufficient=insufficient,
        coverage=coverage,
        threshold=threshold,
        matched_terms=matched,
        missing_terms=missing,
        query_terms=terms,
        reason=reason,
    )


@dataclass
class EvidenceSentence:
    text: str
    chunk_id: str
    doc_id: str
    score: float


def select_sentences(
    query: str, chunks: list[RetrievedChunk], *, limit: int = 4
) -> list[EvidenceSentence]:
    """Pick the sentences that carry the most of the question's terms.

    Fully deterministic: sentences are scored on term overlap, with the parent
    chunk's retrieval rank as the tie-break, then emitted in that order.
    """
    terms = set(content_terms(query))
    if not terms:
        return []

    candidates: list[EvidenceSentence] = []
    for chunk in chunks:
        for raw_sentence in SENTENCE_SPLIT_RE.split(chunk.text):
            sentence = raw_sentence.strip()
            # Skip fragments and markdown scaffolding. Headings and table rows
            # often share the question's vocabulary without asserting anything,
            # so they score well and read as filler in the evidence list.
            if len(sentence) < 25 or set(sentence) <= set("-|# "):
                continue
            if sentence.startswith("#") or sentence.startswith("|"):
                continue
            # A line that is only a bolded or linked title, e.g. "**Added**".
            if sentence.startswith("**") and sentence.endswith("**"):
                continue
            sentence_tokens = set(tokenize(sentence))
            overlap = len(terms & sentence_tokens)
            if overlap == 0:
                continue
            # Normalise by term count, then damp very long sentences slightly so
            # a whole paragraph does not beat a precise one-liner.
            score = (overlap / len(terms)) - (len(sentence) / 20000.0)
            # Rank penalty keeps higher-ranked chunks ahead at equal overlap.
            score -= chunk.rank / 10000.0
            candidates.append(
                EvidenceSentence(
                    text=sentence,
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    score=score,
                )
            )

    candidates.sort(key=lambda item: (-item.score, item.chunk_id, item.text))

    selected: list[EvidenceSentence] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalised = " ".join(candidate.text.lower().split())
        if normalised in seen:
            continue
        seen.add(normalised)
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected
