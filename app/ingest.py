"""Ingestion: validate, sanitise, chunk and persist documents.

Two entry points matter:

* :func:`ingest_text` - a single document from an upload or a corpus file.
* :func:`load_sample_corpus` - idempotent bulk load of ``data/corpus``.

Both go through the same validation and the same content-hash deduplication, so
an uploaded copy of a corpus file is recognised as a duplicate.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .chunking import (
    ParsedDocument,
    chunk_document,
    content_hash,
    make_chunk_id,
    parse_frontmatter,
)
from .config import Settings
from .db import ChunkRecord, Database, DocumentRecord

ALLOWED_SUFFIXES = {".md", ".txt"}
SAFE_STEM_RE = re.compile(r"[^a-z0-9._-]+")


class IngestError(ValueError):
    """Raised for input a caller can fix by sending something different."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class IngestResult:
    doc_id: str
    title: str
    filename: str
    chunk_count: int
    status: str  # "ingested" | "duplicate"
    content_hash: str
    message: str = ""


def sanitize_filename(raw: str) -> str:
    """Reduce an arbitrary client-supplied name to a safe basename.

    Everything directory-like is discarded rather than escaped. We never use the
    result as a filesystem path - it is stored as metadata and shown in the UI -
    but it is sanitised anyway so that a hostile name cannot smuggle traversal
    sequences or control characters into logs and templates.
    """
    if not raw:
        raise IngestError("A filename is required.", "missing_filename")

    # Normalise, then take the basename under both separator conventions.
    candidate = unicodedata.normalize("NFKC", raw).replace("\\", "/")
    candidate = candidate.split("/")[-1]
    candidate = "".join(ch for ch in candidate if ch.isprintable()).strip()
    candidate = candidate.strip(". ")

    if not candidate:
        raise IngestError("Filename is empty after sanitisation.", "unsafe_filename")

    path = Path(candidate)
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise IngestError(
            f"Unsupported file type '{suffix or '(none)'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}.",
            "unsupported_type",
        )

    stem = SAFE_STEM_RE.sub("-", path.stem.lower()).strip("-")
    if not stem:
        raise IngestError("Filename has no usable characters.", "unsafe_filename")

    return f"{stem[:100]}{suffix}"


def decode_upload(data: bytes, *, max_bytes: int) -> str:
    """Enforce the size cap and require valid UTF-8."""
    if len(data) == 0:
        raise IngestError("File is empty.", "empty_file")
    if len(data) > max_bytes:
        raise IngestError(
            f"File is {len(data)} bytes; the limit is {max_bytes} bytes "
            f"({max_bytes // 1024} KiB).",
            "file_too_large",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError(
            "File is not valid UTF-8 text. Only UTF-8 .md and .txt are accepted.",
            "invalid_encoding",
        ) from exc
    if "\x00" in text:
        raise IngestError("File contains NUL bytes.", "invalid_encoding")
    return text


def _derive_doc_id(parsed: ParsedDocument, filename: str, digest: str) -> str:
    """Prefer an explicit frontmatter id; otherwise derive one from the name."""
    declared = parsed.metadata.get("id", "").strip()
    if declared:
        safe = SAFE_STEM_RE.sub("-", declared.lower()).strip("-")
        if safe:
            return safe[:100]
    stem = Path(filename).stem
    return f"{stem[:80]}-{digest[:8]}"


def _derive_title(parsed: ParsedDocument, filename: str) -> str:
    declared = parsed.metadata.get("title", "").strip()
    if declared:
        return declared
    for line in parsed.body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or filename
        if stripped:
            break
    return filename


def ingest_text(
    db: Database,
    settings: Settings,
    *,
    raw_text: str,
    filename: str,
    source: str = "upload",
) -> IngestResult:
    """Validate, chunk and store one document. Idempotent by content hash."""
    safe_name = sanitize_filename(filename)

    if not raw_text.strip():
        raise IngestError("Document contains no text.", "empty_file")

    digest = content_hash(raw_text)
    existing = db.find_by_content_hash(digest)
    if existing is not None:
        document = db.get_document(existing)
        return IngestResult(
            doc_id=existing,
            title=document.title if document else existing,
            filename=document.filename if document else safe_name,
            chunk_count=document.chunk_count if document else 0,
            status="duplicate",
            content_hash=digest,
            message=f"Identical content is already stored as '{existing}'.",
        )

    parsed = parse_frontmatter(raw_text)
    doc_id = _derive_doc_id(parsed, safe_name, digest)
    if db.doc_id_exists(doc_id):
        # Same declared id, different content: keep both, disambiguate the new one.
        doc_id = f"{doc_id}-{digest[:8]}"

    chunks = chunk_document(
        parsed.body,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        line_offset=parsed.body_line_offset,
    )
    if not chunks:
        raise IngestError("Document produced no chunks.", "empty_file")

    chunk_records = [
        ChunkRecord(
            chunk_id=make_chunk_id(doc_id, chunk.ordinal),
            doc_id=doc_id,
            ordinal=chunk.ordinal,
            text=chunk.text,
            heading=chunk.heading,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            char_count=chunk.char_count,
        )
        for chunk in chunks
    ]

    document = DocumentRecord(
        doc_id=doc_id,
        title=_derive_title(parsed, safe_name),
        filename=safe_name,
        content_hash=digest,
        char_count=len(raw_text),
        version=parsed.metadata.get("version"),
        status=parsed.metadata.get("status"),
        supersedes=parsed.metadata.get("supersedes"),
        superseded_by=parsed.metadata.get("superseded_by"),
        product_area=parsed.metadata.get("product_area"),
        source=source,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    db.insert_document(document, raw_text, chunk_records)
    return IngestResult(
        doc_id=doc_id,
        title=document.title,
        filename=safe_name,
        chunk_count=len(chunk_records),
        status="ingested",
        content_hash=digest,
    )


def load_sample_corpus(db: Database, settings: Settings) -> list[IngestResult]:
    """Load every ``.md``/``.txt`` file in the corpus directory.

    Idempotent: re-running after no corpus change reports every document as a
    duplicate and writes nothing.
    """
    corpus_dir = Path(settings.corpus_dir)
    if not corpus_dir.is_dir():
        raise IngestError(
            f"Corpus directory not found: {corpus_dir}", "corpus_missing"
        )

    results: list[IngestResult] = []
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix.lower() not in ALLOWED_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        results.append(
            ingest_text(
                db,
                settings,
                raw_text=text,
                filename=path.name,
                source="sample_corpus",
            )
        )
    return results


def rechunk_all(db: Database, settings: Settings) -> int:
    """Re-derive chunks for every stored document under current settings.

    Used when chunk size or overlap changes: the stored raw text is the source
    of truth, so chunks can be rebuilt without re-uploading anything.
    """
    total = 0
    for document in db.list_documents():
        raw_text = db.get_document_text(document.doc_id)
        if raw_text is None:
            continue
        parsed = parse_frontmatter(raw_text)
        chunks = chunk_document(
            parsed.body,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            line_offset=parsed.body_line_offset,
        )
        db.replace_chunks(
            document.doc_id,
            [
                ChunkRecord(
                    chunk_id=make_chunk_id(document.doc_id, chunk.ordinal),
                    doc_id=document.doc_id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    heading=chunk.heading,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    char_count=chunk.char_count,
                )
                for chunk in chunks
            ],
        )
        total += len(chunks)
    return total
