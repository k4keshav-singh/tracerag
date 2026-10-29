"""Markdown-aware chunking with stable identifiers and source metadata.

The chunker works on whole lines so that every chunk can report an exact,
verifiable line range back into its source document. That matters more than
squeezing chunks to an exact character count: a citation the reader cannot
locate in the original file is not evidence.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FRONTMATTER_FENCE = "---"


@dataclass
class Chunk:
    """One retrievable passage, with everything needed to show its provenance."""

    ordinal: int
    text: str
    heading: str
    start_line: int  # 1-based, inclusive, into the *original* file
    end_line: int  # 1-based, inclusive

    chunk_id: str = ""

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ParsedDocument:
    """A source file split into frontmatter metadata and body text."""

    metadata: dict[str, str] = field(default_factory=dict)
    body: str = ""
    body_line_offset: int = 0  # how many lines of frontmatter were stripped


def parse_frontmatter(text: str) -> ParsedDocument:
    """Parse an optional ``---`` delimited ``key: value`` header.

    Deliberately not YAML: the corpus only uses flat string keys, and a tiny
    parser is one less dependency and one less parsing surface for uploaded
    files. Unknown keys are kept as plain strings.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return ParsedDocument(metadata={}, body=text, body_line_offset=0)

    metadata: dict[str, str] = {}
    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if stripped == FRONTMATTER_FENCE:
            body = "\n".join(lines[index + 1 :])
            return ParsedDocument(
                metadata=metadata, body=body, body_line_offset=index + 1
            )
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if separator:
            metadata[key.strip().lower()] = value.strip()

    # Unterminated frontmatter: treat the whole file as body rather than guess.
    return ParsedDocument(metadata={}, body=text, body_line_offset=0)


def _heading_for_line(headings: list[tuple[int, str]], line_no: int) -> str:
    """Nearest markdown heading at or above ``line_no``; '' if the file has none."""
    current = ""
    for heading_line, heading_text in headings:
        if heading_line <= line_no:
            current = heading_text
        else:
            break
    return current


def chunk_document(
    body: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    line_offset: int = 0,
) -> list[Chunk]:
    """Split ``body`` into overlapping line-aligned chunks.

    ``line_offset`` is added to every reported line number so that callers that
    stripped frontmatter still report line numbers into the original file.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must not be negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    lines = body.split("\n")
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            headings.append((index, match.group(2)))

    chunks: list[Chunk] = []
    start = 0
    total = len(lines)

    while start < total:
        # Skip leading blank lines so chunks never begin with whitespace.
        while start < total and not lines[start].strip():
            start += 1
        if start >= total:
            break

        end = start
        length = 0
        while end < total:
            # +1 for the newline that rejoins this line to the previous one.
            addition = len(lines[end]) + (1 if end > start else 0)
            if length + addition > chunk_size and end > start:
                break
            length += addition
            end += 1

        text = "\n".join(lines[start:end]).strip()
        if text:
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    text=text,
                    heading=_heading_for_line(headings, start),
                    start_line=start + 1 + line_offset,
                    end_line=end + line_offset,
                )
            )

        if end >= total:
            break

        # Walk back from `end` until we have collected at least chunk_overlap
        # characters of trailing context, then start the next chunk there.
        overlap_start = end
        overlap_chars = 0
        while overlap_start > start + 1 and overlap_chars < chunk_overlap:
            overlap_start -= 1
            overlap_chars += len(lines[overlap_start]) + 1

        # Guarantee forward progress even when a single line exceeds chunk_size.
        start = overlap_start if overlap_start > start else end

    return chunks


def content_hash(text: str) -> str:
    """Stable content fingerprint used for deduplicating ingested documents."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_chunk_id(doc_id: str, ordinal: int) -> str:
    """Chunk IDs are human-readable on purpose: they appear in citations."""
    return f"{doc_id}::{ordinal:04d}"
