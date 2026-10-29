"""SQLite persistence for documents, chunks and index bookkeeping.

A single file database is enough here: the corpus is small, reads dominate, and
keeping storage in one file makes "does it survive a restart?" trivially
testable. Connections are opened per operation rather than shared, which keeps
the module safe to use from FastAPI's threadpool without extra locking.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    filename      TEXT NOT NULL,
    content_hash  TEXT NOT NULL UNIQUE,
    raw_text      TEXT NOT NULL,
    char_count    INTEGER NOT NULL,
    version       TEXT,
    status        TEXT,
    supersedes    TEXT,
    superseded_by TEXT,
    product_area  TEXT,
    source        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id   TEXT PRIMARY KEY,
    doc_id     TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ordinal    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    heading    TEXT NOT NULL DEFAULT '',
    start_line INTEGER NOT NULL,
    end_line   INTEGER NOT NULL,
    char_count INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class DocumentRecord:
    doc_id: str
    title: str
    filename: str
    content_hash: str
    char_count: int
    version: str | None
    status: str | None
    supersedes: str | None
    superseded_by: str | None
    product_area: str | None
    source: str
    created_at: str
    chunk_count: int = 0


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    ordinal: int
    text: str
    heading: str
    start_line: int
    end_line: int
    char_count: int


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialise()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialise(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    # --- writes --------------------------------------------------------

    def find_by_content_hash(self, content_hash: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT doc_id FROM documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        return row["doc_id"] if row else None

    def doc_id_exists(self, doc_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
        return row is not None

    def insert_document(
        self, document: DocumentRecord, raw_text: str, chunks: list[ChunkRecord]
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    doc_id, title, filename, content_hash, raw_text, char_count,
                    version, status, supersedes, superseded_by, product_area,
                    source, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    document.doc_id,
                    document.title,
                    document.filename,
                    document.content_hash,
                    raw_text,
                    document.char_count,
                    document.version,
                    document.status,
                    document.supersedes,
                    document.superseded_by,
                    document.product_area,
                    document.source,
                    document.created_at,
                ),
            )
            self._write_chunks(connection, chunks)

    def replace_chunks(self, doc_id: str, chunks: list[ChunkRecord]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            self._write_chunks(connection, chunks)

    @staticmethod
    def _write_chunks(
        connection: sqlite3.Connection, chunks: list[ChunkRecord]
    ) -> None:
        connection.executemany(
            """
            INSERT INTO chunks (
                chunk_id, doc_id, ordinal, text, heading,
                start_line, end_line, char_count
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.ordinal,
                    chunk.text,
                    chunk.heading,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.char_count,
                )
                for chunk in chunks
            ],
        )

    # --- reads ---------------------------------------------------------

    def list_documents(self) -> list[DocumentRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT d.*, COUNT(c.chunk_id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.doc_id = d.doc_id
                GROUP BY d.doc_id
                ORDER BY d.doc_id
                """
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT d.*, COUNT(c.chunk_id) AS chunk_count
                FROM documents d
                LEFT JOIN chunks c ON c.doc_id = d.doc_id
                WHERE d.doc_id = ?
                GROUP BY d.doc_id
                """,
                (doc_id,),
            ).fetchone()
        return _document_from_row(row) if row else None

    def get_document_text(self, doc_id: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT raw_text FROM documents WHERE doc_id = ?", (doc_id,)
            ).fetchone()
        return row["raw_text"] if row else None

    def list_chunks(self) -> list[ChunkRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chunks ORDER BY doc_id, ordinal"
            ).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
        return _chunk_from_row(row) if row else None

    def document_hashes(self) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT doc_id, content_hash FROM documents ORDER BY doc_id"
            ).fetchall()
        return {row["doc_id"]: row["content_hash"] for row in rows}

    def counts(self) -> tuple[int, int]:
        with self.connect() as connection:
            documents = connection.execute(
                "SELECT COUNT(*) AS n FROM documents"
            ).fetchone()["n"]
            chunks = connection.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()[
                "n"
            ]
        return documents, chunks

    # --- index bookkeeping ---------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM index_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO index_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def _document_from_row(row: sqlite3.Row) -> DocumentRecord:
    keys = row.keys()
    return DocumentRecord(
        doc_id=row["doc_id"],
        title=row["title"],
        filename=row["filename"],
        content_hash=row["content_hash"],
        char_count=row["char_count"],
        version=row["version"],
        status=row["status"],
        supersedes=row["supersedes"],
        superseded_by=row["superseded_by"],
        product_area=row["product_area"],
        source=row["source"],
        created_at=row["created_at"],
        chunk_count=row["chunk_count"] if "chunk_count" in keys else 0,
    )


def _chunk_from_row(row: sqlite3.Row) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=row["chunk_id"],
        doc_id=row["doc_id"],
        ordinal=row["ordinal"],
        text=row["text"],
        heading=row["heading"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        char_count=row["char_count"],
    )
