"""Answer construction: extractive by default, optional LLM mode."""

from .evidence import (
    AbstentionDecision,
    EvidenceSentence,
    assess_evidence,
    content_terms,
    select_sentences,
)
from .llm import LLMAnswer, LLMError, build_user_prompt, call_provider, validate_citations
from .pipeline import AnswerResult, answer_question

__all__ = [
    "AbstentionDecision",
    "AnswerResult",
    "EvidenceSentence",
    "LLMAnswer",
    "LLMError",
    "answer_question",
    "assess_evidence",
    "build_user_prompt",
    "call_provider",
    "content_terms",
    "select_sentences",
    "validate_citations",
]
