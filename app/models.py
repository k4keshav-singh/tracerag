"""Request and response schemas for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RetrievalMethod = Literal["keyword", "semantic", "hybrid"]
AnswerMode = Literal["extractive", "llm"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    method: RetrievalMethod = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query must not be blank.")
        return value.strip()


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    method: RetrievalMethod = "hybrid"
    mode: AnswerMode = "extractive"
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank.")
        return value.strip()


class MethodStatusOut(BaseModel):
    name: str
    available: bool
    reason: str | None = None


class StatusOut(BaseModel):
    version: str
    document_count: int
    chunk_count: int
    corpus_fingerprint: str | None
    embedding_model: str
    methods: list[MethodStatusOut]
    llm_configured: bool
    llm_model: str | None
    chunk_size: int
    chunk_overlap: int
    abstain_coverage_threshold: float
    max_upload_bytes: int


class DocumentOut(BaseModel):
    doc_id: str
    title: str
    filename: str
    chunk_count: int
    char_count: int
    version: str | None = None
    status: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    product_area: str | None = None
    source: str
    created_at: str


class ChunkOut(BaseModel):
    chunk_id: str
    doc_id: str
    ordinal: int
    text: str
    heading: str
    start_line: int
    end_line: int
    char_count: int
    doc_title: str | None = None
    filename: str | None = None


class IngestOut(BaseModel):
    doc_id: str
    title: str
    filename: str
    chunk_count: int
    status: str
    content_hash: str
    message: str = ""


class SampleCorpusOut(BaseModel):
    ingested: int
    duplicates: int
    document_count: int
    chunk_count: int
    reindexed: bool
    results: list[IngestOut]


class ErrorOut(BaseModel):
    error: str
    code: str
