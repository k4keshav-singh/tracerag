"""The answering pipeline: retrieve, assess, then answer or abstain."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import Settings
from ..retrieval import RetrievalResult, RetrievalService, RetrievedChunk
from .evidence import AbstentionDecision, assess_evidence, select_sentences
from .llm import LLMError, call_provider

LOGGER = logging.getLogger(__name__)

EXTRACTIVE_LABEL = (
    "Extracted evidence - passages selected from the corpus, not generated "
    "reasoning. No language model wrote this text."
)
LLM_LABEL = (
    "Model-generated answer, constrained to the retrieved passages. Cited IDs "
    "were checked against the retrieved set; that check does not verify that "
    "every claim is supported."
)


@dataclass
class AnswerResult:
    mode: str  # "extractive" | "llm"
    mode_label: str
    answer_text: str
    insufficient_evidence: bool
    citations: list[str]
    retrieval: RetrievalResult
    abstention: AbstentionDecision
    warnings: list[str] = field(default_factory=list)
    provider_error: str | None = None
    fell_back_to_extractive: bool = False
    rejected_citations: list[str] = field(default_factory=list)
    llm_model: str | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "mode_label": self.mode_label,
            "answer": self.answer_text,
            "insufficient_evidence": self.insufficient_evidence,
            "citations": self.citations,
            "rejected_citations": self.rejected_citations,
            "abstention": self.abstention.to_dict(),
            "retrieval": {
                "method": self.retrieval.method,
                "query": self.retrieval.query,
                "elapsed_ms": round(self.retrieval.elapsed_ms, 3),
                "score_semantics": self.retrieval.score_semantics,
                "chunks": [chunk.to_dict() for chunk in self.retrieval.results],
            },
            "warnings": self.warnings,
            "provider_error": self.provider_error,
            "fell_back_to_extractive": self.fell_back_to_extractive,
            "llm_model": self.llm_model,
        }


def _format_insufficient(decision: AbstentionDecision, chunks: list[RetrievedChunk]) -> str:
    lines = [
        "I don't have enough supporting evidence in this corpus to answer that.",
        "",
        decision.reason,
    ]
    if chunks:
        lines.extend(
            [
                "",
                "The closest passages retrieved were:",
                *[
                    f"- {chunk.doc_title} ({chunk.chunk_id})"
                    for chunk in chunks[:3]
                ],
            ]
        )
    return "\n".join(lines)


def _format_extractive(
    question: str, chunks: list[RetrievedChunk], limit: int = 4
) -> tuple[str, list[str]]:
    """Build a deterministic presentation of the supporting passages."""
    sentences = select_sentences(question, chunks, limit=limit)
    if not sentences:
        # Fall back to the leading text of the top chunk rather than nothing.
        if not chunks:
            return ("No supporting passages were retrieved.", [])
        top = chunks[0]
        excerpt = top.text.strip()
        if len(excerpt) > 600:
            excerpt = excerpt[:600].rsplit(" ", 1)[0] + " ..."
        return (
            "No single sentence matched the question closely. The highest-ranked "
            f"passage begins:\n\n{excerpt}",
            [top.chunk_id],
        )

    lines = ["Supporting passages from the corpus:", ""]
    citations: list[str] = []
    for sentence in sentences:
        lines.append(f"- {sentence.text}  [{sentence.chunk_id}]")
        if sentence.chunk_id not in citations:
            citations.append(sentence.chunk_id)
    return ("\n".join(lines), citations)


def answer_question(
    service: RetrievalService,
    settings: Settings,
    *,
    question: str,
    method: str = "hybrid",
    mode: str = "extractive",
    top_k: int | None = None,
) -> AnswerResult:
    """Run the full pipeline for one question."""
    if mode not in {"extractive", "llm"}:
        raise ValueError(f"Unknown answer mode '{mode}'.")

    top_k = top_k or settings.default_top_k
    retrieval = service.search(question, method, top_k)
    chunks = retrieval.results
    warnings = list(retrieval.warnings)

    decision = assess_evidence(
        question,
        chunks,
        threshold=settings.abstain_coverage_threshold,
        evidence_chunks=settings.abstain_evidence_chunks,
    )

    # Conservative behaviour: abstain before spending a provider call.
    if decision.insufficient:
        return AnswerResult(
            mode=mode,
            mode_label=EXTRACTIVE_LABEL if mode == "extractive" else LLM_LABEL,
            answer_text=_format_insufficient(decision, chunks),
            insufficient_evidence=True,
            citations=[],
            retrieval=retrieval,
            abstention=decision,
            warnings=warnings,
        )

    if mode == "extractive":
        answer_text, citations = _format_extractive(question, chunks)
        return AnswerResult(
            mode="extractive",
            mode_label=EXTRACTIVE_LABEL,
            answer_text=answer_text,
            insufficient_evidence=False,
            citations=citations,
            retrieval=retrieval,
            abstention=decision,
            warnings=warnings,
        )

    # --- LLM mode -------------------------------------------------------
    try:
        llm_answer = call_provider(settings, question, chunks)
    except LLMError as exc:
        # Clearly labelled fallback, never a silent substitution.
        LOGGER.warning("LLM provider failed, falling back to extractive: %s", exc)
        answer_text, citations = _format_extractive(question, chunks)
        return AnswerResult(
            mode="extractive",
            mode_label=EXTRACTIVE_LABEL,
            answer_text=answer_text,
            insufficient_evidence=False,
            citations=citations,
            retrieval=retrieval,
            abstention=decision,
            warnings=warnings
            + [
                "LLM mode was requested but the provider call failed. "
                "This answer is extractive, not model-generated."
            ],
            provider_error=str(exc),
            fell_back_to_extractive=True,
        )

    if llm_answer.rejected_citations:
        warnings.append(
            f"The model cited {len(llm_answer.rejected_citations)} chunk ID(s) that "
            "were not in the retrieved context; those citations were dropped."
        )

    return AnswerResult(
        mode="llm",
        mode_label=LLM_LABEL,
        answer_text=llm_answer.answer,
        insufficient_evidence=llm_answer.insufficient_evidence,
        citations=llm_answer.cited_chunk_ids,
        retrieval=retrieval,
        abstention=decision,
        warnings=warnings,
        rejected_citations=llm_answer.rejected_citations,
        llm_model=llm_answer.model,
    )
