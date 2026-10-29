"""FastAPI application: JSON API plus the static frontend."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .answering import answer_question
from .config import Settings, get_settings
from .db import Database
from .ingest import IngestError, decode_upload, ingest_text, load_sample_corpus
from .models import (
    AnswerRequest,
    ChunkOut,
    DocumentOut,
    IngestOut,
    MethodStatusOut,
    SampleCorpusOut,
    SearchRequest,
    StatusOut,
)
from .retrieval import RetrievalService
from .retrieval.embeddings import EmbeddingUnavailable

LOGGER = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
EXAMPLE_QUESTIONS = [
    {
        "label": "Answerable",
        "question": "How long do API keys last before they expire?",
        "note": "A specific fact stated in one current document.",
    },
    {
        "label": "Answerable, needs care",
        "question": "How many times does NimbusDesk retry a failed webhook delivery?",
        "note": "The corpus distinguishes 6 retries from 7 total attempts.",
    },
    {
        "label": "Not in the corpus",
        "question": "What is NimbusDesk's phone support number?",
        "note": "Nothing in the corpus answers this; expect an abstention.",
    },
    {
        "label": "Version conflict",
        "question": "Do workspace tokens expire?",
        "note": "A superseded 2.3 page says no; the current 2.4 page says keys expire.",
    },
    {
        "label": "Paraphrase",
        "question": "What is the largest page size a list endpoint will return?",
        "note": "The corpus says 'maximum accepted value is 200' without the word 'page size'.",
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings.db_path)
        service = RetrievalService(database, settings)
        # Build at start-up so the first request is not charged for it, and so
        # an unavailable embedding model is reported immediately.
        service.ensure_index(force=True)
        app.state.settings = settings
        app.state.db = database
        app.state.service = service
        documents, chunks = database.counts()
        LOGGER.info(
            "TraceRAG ready: %d documents, %d chunks, methods=%s",
            documents,
            chunks,
            ",".join(service.available_methods()),
        )
        yield

    app = FastAPI(
        title="TraceRAG",
        version=__version__,
        description=(
            "Evidence-backed document Q&A over a synthetic corpus, with "
            "keyword, semantic and hybrid retrieval and a reproducible "
            "retrieval benchmark."
        ),
        lifespan=lifespan,
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(IngestError)
    async def _ingest_error_handler(_: Request, exc: IngestError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc), "code": exc.code})

    @app.exception_handler(EmbeddingUnavailable)
    async def _embedding_error_handler(
        _: Request, exc: EmbeddingUnavailable
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "code": "method_unavailable"},
        )

    # --- pages ---------------------------------------------------------

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="Frontend not built.")
        return FileResponse(page)

    @app.get("/healthz", include_in_schema=False)
    async def healthz(request: Request) -> dict:
        documents, chunks = request.app.state.db.counts()
        return {"status": "ok", "documents": documents, "chunks": chunks}

    # --- status and metadata --------------------------------------------

    @app.get("/api/status", response_model=StatusOut)
    async def status(request: Request) -> StatusOut:
        service: RetrievalService = request.app.state.service
        database: Database = request.app.state.db
        documents, chunks = database.counts()
        statuses = service.method_status()
        return StatusOut(
            version=__version__,
            document_count=documents,
            chunk_count=chunks,
            corpus_fingerprint=service.corpus_fingerprint,
            embedding_model=settings.embedding_model,
            methods=[
                MethodStatusOut(name=name, available=item.available, reason=item.reason)
                for name, item in statuses.items()
            ],
            llm_configured=settings.llm_configured,
            # The model name is not a secret; the key and base URL are not returned.
            llm_model=settings.llm_model if settings.llm_configured else None,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            abstain_coverage_threshold=settings.abstain_coverage_threshold,
            max_upload_bytes=settings.max_upload_bytes,
        )

    @app.get("/api/examples")
    async def examples() -> dict:
        return {"examples": EXAMPLE_QUESTIONS}

    @app.get("/api/benchmark")
    async def benchmark() -> dict:
        """Serve the most recent checked-in benchmark run, if there is one."""
        report = Path(settings.data_dir).parent / "reports" / "benchmark.json"
        if not report.is_file():
            return {
                "available": False,
                "message": (
                    "No benchmark report found. Generate one with: "
                    "python -m app.evaluate --split test"
                ),
            }
        try:
            return {"available": True, "report": json.loads(report.read_text("utf-8"))}
        except (OSError, json.JSONDecodeError) as exc:
            return {"available": False, "message": f"Could not read report: {exc}"}

    # --- documents --------------------------------------------------------

    @app.get("/api/documents", response_model=list[DocumentOut])
    async def list_documents(request: Request) -> list[DocumentOut]:
        database: Database = request.app.state.db
        return [
            DocumentOut(
                doc_id=document.doc_id,
                title=document.title,
                filename=document.filename,
                chunk_count=document.chunk_count,
                char_count=document.char_count,
                version=document.version,
                status=document.status,
                supersedes=document.supersedes,
                superseded_by=document.superseded_by,
                product_area=document.product_area,
                source=document.source,
                created_at=document.created_at,
            )
            for document in database.list_documents()
        ]

    @app.get("/api/documents/{doc_id}")
    async def get_document(request: Request, doc_id: str) -> dict:
        database: Database = request.app.state.db
        document = database.get_document(doc_id)
        if document is None:
            raise HTTPException(status_code=404, detail=f"No document '{doc_id}'.")
        chunks = [chunk for chunk in database.list_chunks() if chunk.doc_id == doc_id]
        return {
            "document": DocumentOut(
                doc_id=document.doc_id,
                title=document.title,
                filename=document.filename,
                chunk_count=document.chunk_count,
                char_count=document.char_count,
                version=document.version,
                status=document.status,
                supersedes=document.supersedes,
                superseded_by=document.superseded_by,
                product_area=document.product_area,
                source=document.source,
                created_at=document.created_at,
            ).model_dump(),
            "chunks": [
                ChunkOut(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    heading=chunk.heading,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    char_count=chunk.char_count,
                ).model_dump()
                for chunk in chunks
            ],
        }

    @app.get("/api/chunks/{chunk_id:path}", response_model=ChunkOut)
    async def get_chunk(request: Request, chunk_id: str) -> ChunkOut:
        database: Database = request.app.state.db
        chunk = database.get_chunk(chunk_id)
        if chunk is None:
            raise HTTPException(status_code=404, detail=f"No chunk '{chunk_id}'.")
        document = database.get_document(chunk.doc_id)
        return ChunkOut(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            ordinal=chunk.ordinal,
            text=chunk.text,
            heading=chunk.heading,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            char_count=chunk.char_count,
            doc_title=document.title if document else None,
            filename=document.filename if document else None,
        )

    @app.post("/api/documents", response_model=IngestOut)
    async def upload_document(request: Request, file: UploadFile = File(...)) -> IngestOut:
        database: Database = request.app.state.db
        service: RetrievalService = request.app.state.service

        data = await file.read()
        text = decode_upload(data, max_bytes=settings.max_upload_bytes)
        result = ingest_text(
            database,
            settings,
            raw_text=text,
            filename=file.filename or "upload.txt",
            source="upload",
        )
        if result.status == "ingested":
            service.ensure_index()
        return IngestOut(**vars(result))

    @app.post("/api/sample-corpus", response_model=SampleCorpusOut)
    async def post_sample_corpus(request: Request) -> SampleCorpusOut:
        database: Database = request.app.state.db
        service: RetrievalService = request.app.state.service

        results = load_sample_corpus(database, settings)
        ingested = sum(1 for item in results if item.status == "ingested")
        reindexed = service.ensure_index() if ingested else False
        documents, chunks = database.counts()
        return SampleCorpusOut(
            ingested=ingested,
            duplicates=len(results) - ingested,
            document_count=documents,
            chunk_count=chunks,
            reindexed=reindexed,
            results=[IngestOut(**vars(item)) for item in results],
        )

    # --- retrieval and answering -------------------------------------------

    @app.post("/api/search")
    async def search(request: Request, payload: SearchRequest) -> dict:
        service: RetrievalService = request.app.state.service
        result = service.search(payload.query, payload.method, payload.top_k)
        return {
            "method": result.method,
            "query": result.query,
            "elapsed_ms": round(result.elapsed_ms, 3),
            "score_semantics": result.score_semantics,
            "warnings": result.warnings,
            "results": [chunk.to_dict() for chunk in result.results],
        }

    @app.post("/api/answer")
    async def answer(request: Request, payload: AnswerRequest) -> dict:
        service: RetrievalService = request.app.state.service
        if payload.mode == "llm" and not settings.llm_configured:
            raise HTTPException(
                status_code=400,
                detail=(
                    "LLM mode is not configured on this server. Set LLM_BASE_URL, "
                    "LLM_API_KEY and LLM_MODEL, or use extractive mode."
                ),
            )
        result = answer_question(
            service,
            settings,
            question=payload.question,
            method=payload.method,
            mode=payload.mode,
            top_k=payload.top_k,
        )
        return result.to_dict()

    return app


app = create_app()
