"""End-to-end HTTP smoke test against a running TraceRAG server.

    python -m scripts.smoke_test --base-url http://127.0.0.1:8000

Covers the path a reviewer actually walks: load the sample corpus, list
documents, retrieve with every available method, answer an answerable question
with citations that resolve, and confirm an out-of-corpus question is refused.

Exits non-zero on the first failure, so it works as a CI gate.
"""

from __future__ import annotations

import argparse
import sys

import httpx

PASS = "PASS"
FAIL = "FAIL"


class SmokeFailure(AssertionError):
    pass


def check(condition: bool, label: str, detail: str = "") -> None:
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f" - {detail}" if detail else ""))
    if not condition:
        raise SmokeFailure(label)


def run(base_url: str, timeout: float) -> int:
    client = httpx.Client(base_url=base_url, timeout=timeout)
    try:
        print("health")
        health = client.get("/healthz")
        check(health.status_code == 200, "GET /healthz is 200", str(health.status_code))

        print("sample corpus")
        loaded = client.post("/api/sample-corpus")
        check(loaded.status_code == 200, "POST /api/sample-corpus is 200")
        corpus = loaded.json()
        check(
            corpus["document_count"] >= 15,
            "corpus has at least 15 documents",
            f"{corpus['document_count']} documents, {corpus['chunk_count']} chunks",
        )

        repeat = client.post("/api/sample-corpus").json()
        check(repeat["ingested"] == 0, "re-loading the corpus is idempotent")

        print("status")
        status = client.get("/api/status").json()
        available = [item["name"] for item in status["methods"] if item["available"]]
        unavailable = [item for item in status["methods"] if not item["available"]]
        check("keyword" in available, "keyword retrieval is available")
        for item in unavailable:
            print(f"      note: {item['name']} unavailable - {item['reason']}")

        print("documents")
        documents = client.get("/api/documents").json()
        check(len(documents) == corpus["document_count"], "document listing matches count")
        superseded = [d for d in documents if d["status"] == "superseded"]
        check(len(superseded) >= 1, "corpus contains a superseded document",
              superseded[0]["doc_id"] if superseded else "")

        print("retrieval")
        for method in available:
            response = client.post(
                "/api/search",
                json={"query": "webhook retry schedule", "method": method, "top_k": 5},
            )
            check(response.status_code == 200, f"search with {method} is 200")
            payload = response.json()
            check(len(payload["results"]) > 0, f"{method} returned results",
                  f"{len(payload['results'])} chunks in {payload['elapsed_ms']}ms")
            check(
                bool(payload["score_semantics"]),
                f"{method} explains its score scale",
            )

        print("answering")
        answered = client.post(
            "/api/answer",
            json={
                "question": "How long before an API key expires?",
                "method": available[-1],
                "mode": "extractive",
                "top_k": 5,
            },
        ).json()
        check(answered["insufficient_evidence"] is False, "answerable question was answered")
        check(bool(answered["citations"]), "answer carries citations",
              ", ".join(answered["citations"][:3]))

        retrieved_ids = {c["chunk_id"] for c in answered["retrieval"]["chunks"]}
        check(
            set(answered["citations"]) <= retrieved_ids,
            "every citation came from the retrieved context",
        )

        print("citation resolution")
        first_citation = answered["citations"][0]
        chunk = client.get(f"/api/chunks/{first_citation}")
        check(chunk.status_code == 200, "citation resolves to a chunk", first_citation)
        chunk_body = chunk.json()
        check(bool(chunk_body["text"]), "chunk has text")
        check(chunk_body["start_line"] >= 1, "chunk reports a source line range",
              f"lines {chunk_body['start_line']}-{chunk_body['end_line']}")

        print("abstention")
        refused = client.post(
            "/api/answer",
            json={
                "question": "What is the best wine pairing for grilled salmon?",
                "method": available[-1],
                "mode": "extractive",
            },
        ).json()
        check(refused["insufficient_evidence"] is True, "out-of-corpus question was refused")
        check(refused["citations"] == [], "a refusal cites nothing")

        print("upload validation")
        oversized = client.post(
            "/api/documents",
            files={"file": ("big.md", b"x" * (status["max_upload_bytes"] + 1), "text/markdown")},
        )
        check(oversized.status_code == 400, "oversized upload is rejected")
        check(oversized.json()["code"] == "file_too_large", "rejection names the reason")

        bad_type = client.post(
            "/api/documents", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}
        )
        check(bad_type.status_code == 400, "unsupported file type is rejected")

        print("\nSmoke test passed.")
        return 0
    except SmokeFailure as exc:
        print(f"\nSmoke test FAILED: {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"\nSmoke test could not reach the server: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.smoke_test")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    print(f"TraceRAG smoke test against {args.base_url}\n")
    return run(args.base_url.rstrip("/"), args.timeout)


if __name__ == "__main__":
    sys.exit(main())
