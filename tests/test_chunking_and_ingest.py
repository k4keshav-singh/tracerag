"""Chunking, source metadata, deduplication and upload validation."""

from __future__ import annotations

import pytest

from app.chunking import chunk_document, content_hash, parse_frontmatter
from app.db import Database
from app.ingest import (
    IngestError,
    decode_upload,
    ingest_text,
    load_sample_corpus,
    rechunk_all,
    sanitize_filename,
)

LONG_BODY = "\n".join(f"Line {index} of the body with enough words to matter." for index in range(60))


# --- chunk overlap and source metadata ------------------------------------


def test_chunks_overlap_and_cover_the_whole_body():
    chunks = chunk_document(LONG_BODY, chunk_size=400, chunk_overlap=120)

    assert len(chunks) > 1, "body should split into several chunks"

    for earlier, later in zip(chunks, chunks[1:]):
        # Consecutive chunks must share at least one line, and must advance.
        assert later.start_line <= earlier.end_line, "chunks should overlap"
        assert later.start_line > earlier.start_line, "chunks must make progress"

    # Every line of the body appears in some chunk.
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.start_line, chunk.end_line + 1))
    assert covered.issuperset(range(1, LONG_BODY.count("\n") + 2))


def test_overlap_text_is_actually_repeated():
    chunks = chunk_document(LONG_BODY, chunk_size=400, chunk_overlap=120)
    first, second = chunks[0], chunks[1]
    overlap_lines = set(range(second.start_line, first.end_line + 1))
    assert overlap_lines, "expected a non-empty overlap region"

    shared = [line for line in first.text.split("\n") if line in second.text.split("\n")]
    assert shared, "overlapping chunks should share literal lines"


def test_chunk_records_heading_and_line_range():
    body = "# Alpha\n\nFirst section body text here.\n\n## Beta\n\nSecond section body text."
    chunks = chunk_document(body, chunk_size=10_000, chunk_overlap=0)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.heading == "Alpha"
    assert chunk.start_line == 1
    assert chunk.end_line == len(body.split("\n"))


def test_line_numbers_point_into_the_original_file_after_frontmatter():
    raw = "---\nid: doc-x\ntitle: Doc X\n---\n# Heading\n\nBody sentence one.\n"
    parsed = parse_frontmatter(raw)
    chunks = chunk_document(
        parsed.body, chunk_size=10_000, chunk_overlap=0, line_offset=parsed.body_line_offset
    )
    original_lines = raw.split("\n")
    chunk = chunks[0]
    # The reported start line must really be the heading in the original file.
    assert original_lines[chunk.start_line - 1] == "# Heading"


def test_chunk_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_document("text", chunk_size=100, chunk_overlap=100)


# --- deduplication and persistence ----------------------------------------


def test_identical_content_is_deduplicated(db: Database, settings):
    text = "---\nid: dup-doc\ntitle: Dup\n---\n# Dup\n\nSome body text for the document.\n"

    first = ingest_text(db, settings, raw_text=text, filename="a.md")
    second = ingest_text(db, settings, raw_text=text, filename="different-name.md")

    assert first.status == "ingested"
    assert second.status == "duplicate"
    assert second.doc_id == first.doc_id
    assert db.counts()[0] == 1


def test_same_doc_id_different_content_is_kept_separately(db: Database, settings):
    base = "---\nid: same-id\ntitle: T\n---\n# T\n\n{}\n"
    first = ingest_text(db, settings, raw_text=base.format("Body one here."), filename="a.md")
    second = ingest_text(db, settings, raw_text=base.format("Body two differs."), filename="b.md")

    assert second.status == "ingested"
    assert second.doc_id != first.doc_id
    assert db.counts()[0] == 2


def test_sample_corpus_load_is_idempotent(db: Database, settings):
    first = load_sample_corpus(db, settings)
    counts_after_first = db.counts()

    second = load_sample_corpus(db, settings)

    assert all(item.status == "ingested" for item in first)
    assert all(item.status == "duplicate" for item in second)
    assert db.counts() == counts_after_first


def test_data_survives_reopening_the_database(db: Database, settings):
    load_sample_corpus(db, settings)
    expected = db.counts()

    # A brand-new Database object against the same file: this is what a restart
    # looks like from the application's point of view.
    reopened = Database(settings.db_path)

    assert reopened.counts() == expected
    assert reopened.get_document("nd-auth-005") is not None
    assert reopened.get_chunk("nd-auth-005::0000") is not None


def test_rechunking_rebuilds_from_stored_text(db: Database, settings):
    load_sample_corpus(db, settings)
    original_chunks = db.counts()[1]

    settings.chunk_size = 300
    settings.chunk_overlap = 60
    new_total = rechunk_all(db, settings)

    assert new_total > original_chunks, "smaller chunks should produce more of them"
    assert db.counts()[1] == new_total
    assert db.counts()[0] == 18, "rechunking must not change the document count"


# --- upload validation ------------------------------------------------------


def test_oversized_upload_is_rejected():
    with pytest.raises(IngestError) as info:
        decode_upload(b"x" * 2048, max_bytes=1024)
    assert info.value.code == "file_too_large"


def test_empty_upload_is_rejected():
    with pytest.raises(IngestError) as info:
        decode_upload(b"", max_bytes=1024)
    assert info.value.code == "empty_file"


def test_non_utf8_upload_is_rejected():
    with pytest.raises(IngestError) as info:
        decode_upload(b"\xff\xfe\x00bad", max_bytes=1024)
    assert info.value.code == "invalid_encoding"


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd.md",
        "..\\..\\windows\\system32\\config.txt",
        "/absolute/path/notes.md",
        "C:\\Users\\someone\\secret.txt",
    ],
)
def test_path_traversal_filenames_are_flattened(name):
    safe = sanitize_filename(name)
    assert "/" not in safe and "\\" not in safe
    assert ".." not in safe
    assert safe.endswith((".md", ".txt"))


@pytest.mark.parametrize("name", ["notes.pdf", "archive.zip", "script.py", "noextension"])
def test_unsupported_extensions_are_rejected(name):
    with pytest.raises(IngestError) as info:
        sanitize_filename(name)
    assert info.value.code == "unsupported_type"


def test_filename_with_only_unsafe_characters_is_rejected():
    with pytest.raises(IngestError) as info:
        sanitize_filename("***.md")
    assert info.value.code == "unsafe_filename"


def test_sanitised_filename_keeps_something_recognisable():
    assert sanitize_filename("My Release Notes (v2).MD") == "my-release-notes-v2.md"


def test_content_hash_is_stable_and_content_sensitive():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
