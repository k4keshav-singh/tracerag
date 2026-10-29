"""Idempotent sample-corpus loader.

    python -m scripts.load_corpus

Safe to run repeatedly: documents are deduplicated by content hash, so a second
run ingests nothing and reports every document as already present.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.config import get_settings
from app.db import Database
from app.ingest import load_sample_corpus
from app.retrieval import RetrievalService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.load_corpus")
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Ingest only; do not build the retrieval index (skips model download).",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    settings = get_settings()
    db = Database(settings.db_path)

    results = load_sample_corpus(db, settings)
    ingested = [item for item in results if item.status == "ingested"]
    duplicates = [item for item in results if item.status == "duplicate"]

    for item in ingested:
        print(f"  + {item.doc_id:32s} {item.chunk_count:3d} chunks  {item.title}")
    for item in duplicates:
        print(f"  = {item.doc_id:32s} already present")

    documents, chunks = db.counts()
    print(
        f"\n{len(ingested)} ingested, {len(duplicates)} already present. "
        f"Corpus is now {documents} documents / {chunks} chunks."
    )

    if args.skip_index:
        print("Index build skipped (--skip-index).")
        return 0

    service = RetrievalService(db, settings)
    service.ensure_index(force=True)
    statuses = service.method_status()
    print("\nRetrieval methods:")
    for name, status in statuses.items():
        if status.available:
            print(f"  {name:9s} available")
        else:
            print(f"  {name:9s} UNAVAILABLE - {status.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
