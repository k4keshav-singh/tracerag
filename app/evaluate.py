"""Reproducible retrieval evaluation.

Run it with::

    python -m app.evaluate --split test

What it measures, and what it deliberately does not:

* **Document-level Recall@5** - retrieved chunks are deduplicated to documents
  (keeping each document's best rank), and recall is the fraction of a
  question's labelled relevant documents that appear in the top 5 *documents*.
* **MRR@10** - reciprocal rank of the first relevant document within the top 10
  documents, averaged over answerable questions.
* **Latency** - wall-clock retrieval time for the application's default
  ``top_k``, measured after warm-up queries that are discarded.
* **Abstention** - how often the insufficient-evidence heuristic fires on
  unanswerable questions (correct) and on answerable ones (a false refusal).
* **Citation validity** - whether every cited chunk ID was in the retrieved
  context. This is an identifier check. It is *not* a measure of whether the
  answer is factually correct, and this report never presents it as one.

Semantic correctness is not scored automatically. Doing so would need either an
LLM judge or human grading; the default benchmark makes no paid calls.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .answering import assess_evidence
from .config import Settings, get_settings
from .db import Database
from .retrieval import METHODS, RetrievalService
from .retrieval.embeddings import EmbeddingUnavailable

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALUATION_DIR = REPO_ROOT / "evaluation"
REPORTS_DIR = REPO_ROOT / "reports"

# Chunks pulled per query for the ranking metrics. Deep enough that at least ten
# distinct documents are usually available for MRR@10 over an 18-document corpus.
RANKING_DEPTH = 30
WARMUP_QUERIES = 3


# --- fixtures ------------------------------------------------------------


@dataclass
class Question:
    id: str
    question: str
    type: str
    answerable: bool
    relevant_doc_ids: list[str]
    reference_fact: str


def load_questions(split: str) -> tuple[list[Question], dict]:
    path = EVALUATION_DIR / f"{split}_questions.json"
    if not path.is_file():
        raise SystemExit(f"No fixture file at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = [
        Question(
            id=item["id"],
            question=item["question"],
            type=item["type"],
            answerable=item["answerable"],
            relevant_doc_ids=list(item.get("relevant_doc_ids") or []),
            reference_fact=item.get("reference_fact", ""),
        )
        for item in payload["questions"]
    ]
    return questions, payload


def validate_labels(questions: list[Question], db: Database) -> list[str]:
    """Check every labelled document ID actually exists in the corpus."""
    known = {document.doc_id for document in db.list_documents()}
    problems: list[str] = []
    for question in questions:
        if question.answerable and not question.relevant_doc_ids:
            problems.append(f"{question.id}: answerable but no relevant_doc_ids")
        if not question.answerable and question.relevant_doc_ids:
            problems.append(f"{question.id}: unanswerable but has relevant_doc_ids")
        for doc_id in question.relevant_doc_ids:
            if doc_id not in known:
                problems.append(f"{question.id}: unknown doc_id '{doc_id}'")
    return problems


# --- metric helpers -------------------------------------------------------


def documents_in_rank_order(chunks) -> list[str]:
    """Collapse a chunk ranking to a document ranking, keeping best rank."""
    seen: list[str] = []
    for chunk in chunks:
        if chunk.doc_id not in seen:
            seen.append(chunk.doc_id)
    return seen


def recall_at_k(retrieved_docs: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return float("nan")
    top = set(retrieved_docs[:k])
    return len(top & set(relevant)) / len(relevant)


def hit_at_k(retrieved_docs: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return float("nan")
    return 1.0 if set(retrieved_docs[:k]) & set(relevant) else 0.0


def reciprocal_rank(retrieved_docs: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return float("nan")
    relevant_set = set(relevant)
    for position, doc_id in enumerate(retrieved_docs[:k], start=1):
        if doc_id in relevant_set:
            return 1.0 / position
    return 0.0


def _mean(values: list[float]) -> float | None:
    usable = [value for value in values if value == value]  # drop NaN
    return statistics.fmean(usable) if usable else None


# --- evaluation core -------------------------------------------------------


@dataclass
class QuestionResult:
    question_id: str
    question: str
    type: str
    answerable: bool
    relevant_doc_ids: list[str]
    retrieved_doc_ids: list[str]
    top_chunk_ids: list[str]
    recall_at_5: float
    hit_at_5: float
    reciprocal_rank_at_10: float
    abstained: bool
    abstention_correct: bool
    coverage: float
    latency_ms: float
    citations_valid: bool
    notes: str = ""

    def to_dict(self) -> dict:
        def clean(value: float) -> Any:
            return None if value != value else round(value, 4)

        return {
            "question_id": self.question_id,
            "question": self.question,
            "type": self.type,
            "answerable": self.answerable,
            "relevant_doc_ids": self.relevant_doc_ids,
            "retrieved_doc_ids": self.retrieved_doc_ids[:10],
            "top_chunk_ids": self.top_chunk_ids,
            "recall_at_5": clean(self.recall_at_5),
            "hit_at_5": clean(self.hit_at_5),
            "reciprocal_rank_at_10": clean(self.reciprocal_rank_at_10),
            "abstained": self.abstained,
            "abstention_correct": self.abstention_correct,
            "coverage": round(self.coverage, 4),
            "latency_ms": round(self.latency_ms, 3),
            "citations_valid": self.citations_valid,
            "notes": self.notes,
        }


@dataclass
class MethodReport:
    name: str
    available: bool
    reason: str | None = None
    results: list[QuestionResult] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)

    def summary(self) -> dict:
        if not self.available:
            return {"available": False, "reason": self.reason}

        answerable = [item for item in self.results if item.answerable]
        unanswerable = [item for item in self.results if not item.answerable]

        correct_abstentions = [item for item in unanswerable if item.abstained]
        false_refusals = [item for item in answerable if item.abstained]

        latencies = sorted(self.latencies)
        percentile_95 = (
            latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))]
            if latencies
            else None
        )

        return {
            "available": True,
            "question_count": len(self.results),
            "answerable_count": len(answerable),
            "unanswerable_count": len(unanswerable),
            "doc_recall_at_5": _mean([item.recall_at_5 for item in answerable]),
            "doc_hit_at_5": _mean([item.hit_at_5 for item in answerable]),
            "mrr_at_10": _mean([item.reciprocal_rank_at_10 for item in answerable]),
            "abstention_rate_unanswerable": (
                len(correct_abstentions) / len(unanswerable) if unanswerable else None
            ),
            "false_refusal_rate_answerable": (
                len(false_refusals) / len(answerable) if answerable else None
            ),
            "citation_validity_rate": (
                sum(1 for item in self.results if item.citations_valid) / len(self.results)
                if self.results
                else None
            ),
            "latency_ms_mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "latency_ms_median": round(statistics.median(latencies), 3) if latencies else None,
            "latency_ms_p95": round(percentile_95, 3) if percentile_95 is not None else None,
            "latency_ms_min": round(min(latencies), 3) if latencies else None,
            "latency_ms_max": round(max(latencies), 3) if latencies else None,
        }


def evaluate_method(
    service: RetrievalService,
    settings: Settings,
    questions: list[Question],
    method: str,
    *,
    top_k: int,
) -> MethodReport:
    status = service.method_status()[method]
    if not status.available:
        return MethodReport(name=method, available=False, reason=status.reason)

    report = MethodReport(name=method, available=True)

    # Warm-up queries are run and discarded so the first-call cost (lazy model
    # load, allocator warm-up) does not land in the reported latency.
    for index in range(WARMUP_QUERIES):
        service.search(questions[index % len(questions)].question, method, top_k)

    for question in questions:
        # Deep retrieval for the ranking metrics.
        ranking = service.search(question.question, method, RANKING_DEPTH)
        retrieved_docs = documents_in_rank_order(ranking.results)

        # A second search at the application's default top_k. This is the call
        # we time, because it is the one a user actually waits on.
        start = time.perf_counter()
        serving = service.search(question.question, method, top_k)
        latency_ms = (time.perf_counter() - start) * 1000.0

        decision = assess_evidence(
            question.question,
            serving.results,
            threshold=settings.abstain_coverage_threshold,
            evidence_chunks=settings.abstain_evidence_chunks,
        )

        abstained = decision.insufficient
        abstention_correct = abstained != question.answerable

        # Extractive mode cites only chunk IDs taken from the retrieved set, so
        # this is True by construction here. It is still computed and reported,
        # because the same field is meaningful when an LLM produced the answer.
        retrieved_ids = {chunk.chunk_id for chunk in serving.results}
        citations_valid = all(
            chunk.chunk_id in retrieved_ids for chunk in serving.results
        )

        report.latencies.append(latency_ms)
        report.results.append(
            QuestionResult(
                question_id=question.id,
                question=question.question,
                type=question.type,
                answerable=question.answerable,
                relevant_doc_ids=question.relevant_doc_ids,
                retrieved_doc_ids=retrieved_docs,
                top_chunk_ids=[chunk.chunk_id for chunk in serving.results],
                recall_at_5=recall_at_k(retrieved_docs, question.relevant_doc_ids, 5),
                hit_at_5=hit_at_k(retrieved_docs, question.relevant_doc_ids, 5),
                reciprocal_rank_at_10=reciprocal_rank(
                    retrieved_docs, question.relevant_doc_ids, 10
                ),
                abstained=abstained,
                abstention_correct=abstention_correct,
                coverage=decision.coverage,
                latency_ms=latency_ms,
                citations_valid=citations_valid,
            )
        )

    return report


# --- abstention calibration -------------------------------------------------


def calibrate_threshold(
    service: RetrievalService,
    settings: Settings,
    questions: list[Question],
    method: str,
    *,
    top_k: int,
) -> dict:
    """Sweep the coverage threshold on the given (development) questions.

    Returns the sweep table and the value that maximises balanced accuracy
    between correctly refusing unanswerable questions and not refusing
    answerable ones. Ties go to the lower threshold, which refuses less.
    """
    status = service.method_status()[method]
    if not status.available:
        return {"available": False, "reason": status.reason}

    coverages: list[tuple[Question, float]] = []
    for question in questions:
        result = service.search(question.question, method, top_k)
        decision = assess_evidence(
            question.question,
            result.results,
            threshold=0.0,
            evidence_chunks=settings.abstain_evidence_chunks,
        )
        coverages.append((question, decision.coverage))

    answerable = [item for item in coverages if item[0].answerable]
    unanswerable = [item for item in coverages if not item[0].answerable]

    sweep: list[dict] = []
    for step in range(0, 21):
        threshold = step / 20.0
        true_refusals = sum(1 for _, coverage in unanswerable if coverage < threshold)
        false_refusals = sum(1 for _, coverage in answerable if coverage < threshold)
        refusal_recall = true_refusals / len(unanswerable) if unanswerable else 0.0
        answer_retention = (
            1.0 - (false_refusals / len(answerable)) if answerable else 0.0
        )
        sweep.append(
            {
                "threshold": round(threshold, 2),
                "correct_refusals": true_refusals,
                "unanswerable_total": len(unanswerable),
                "false_refusals": false_refusals,
                "answerable_total": len(answerable),
                "refusal_recall": round(refusal_recall, 4),
                "answer_retention": round(answer_retention, 4),
                "balanced_accuracy": round((refusal_recall + answer_retention) / 2.0, 4),
            }
        )

    best = max(sweep, key=lambda row: (row["balanced_accuracy"], -row["threshold"]))
    return {
        "available": True,
        "method": method,
        "sweep": sweep,
        "selected_threshold": best["threshold"],
        "selected_balanced_accuracy": best["balanced_accuracy"],
        "configured_threshold": settings.abstain_coverage_threshold,
        "note": (
            "Swept on development questions only. The configured threshold is "
            "whatever ABSTAIN_COVERAGE_THRESHOLD is set to; it is not changed "
            "automatically by this command."
        ),
    }


# --- reporting ---------------------------------------------------------------


def representative_failures(report: MethodReport, limit: int = 4) -> list[dict]:
    """Pick the most instructive failures: missed retrievals and bad refusals."""
    failures: list[tuple[int, dict]] = []
    for item in report.results:
        if item.answerable and item.hit_at_5 == 0.0:
            failures.append(
                (
                    0,
                    {
                        "question_id": item.question_id,
                        "question": item.question,
                        "type": item.type,
                        "failure": "no relevant document in the top 5",
                        "expected_doc_ids": item.relevant_doc_ids,
                        "retrieved_doc_ids": item.retrieved_doc_ids[:5],
                    },
                )
            )
        elif item.answerable and item.abstained:
            failures.append(
                (
                    1,
                    {
                        "question_id": item.question_id,
                        "question": item.question,
                        "type": item.type,
                        "failure": "refused an answerable question",
                        "coverage": round(item.coverage, 3),
                        "expected_doc_ids": item.relevant_doc_ids,
                        "retrieved_doc_ids": item.retrieved_doc_ids[:5],
                    },
                )
            )
        elif not item.answerable and not item.abstained:
            failures.append(
                (
                    2,
                    {
                        "question_id": item.question_id,
                        "question": item.question,
                        "type": item.type,
                        "failure": "answered an unanswerable question",
                        "coverage": round(item.coverage, 3),
                        "retrieved_doc_ids": item.retrieved_doc_ids[:3],
                    },
                )
            )
        elif item.answerable and item.recall_at_5 < 1.0:
            failures.append(
                (
                    3,
                    {
                        "question_id": item.question_id,
                        "question": item.question,
                        "type": item.type,
                        "failure": "only part of the labelled relevant set was retrieved",
                        "expected_doc_ids": item.relevant_doc_ids,
                        "retrieved_doc_ids": item.retrieved_doc_ids[:5],
                    },
                )
            )
    failures.sort(key=lambda pair: pair[0])
    return [payload for _, payload in failures[:limit]]


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add("# TraceRAG retrieval benchmark")
    add("")
    add(f"- **Split:** `{report['split']}` ({report['question_count']} questions)")
    add(f"- **Run:** {report['run_timestamp']}")
    add(f"- **Corpus:** {report['document_count']} documents, {report['chunk_count']} chunks")
    add(f"- **Corpus fingerprint:** `{report['corpus_fingerprint']}`")
    add(f"- **Embedding model:** `{report['embedding_model']}`")
    add(
        f"- **Retrieval settings:** chunk_size={report['settings']['chunk_size']}, "
        f"chunk_overlap={report['settings']['chunk_overlap']}, "
        f"rrf_k={report['settings']['rrf_k']}, "
        f"serving_top_k={report['settings']['serving_top_k']}, "
        f"ranking_depth={report['settings']['ranking_depth']}"
    )
    add(
        f"- **Abstention threshold:** {report['settings']['abstain_coverage_threshold']} "
        "(content-term coverage)"
    )
    add(f"- **Environment:** {report['environment']['python']} on {report['environment']['platform']}")
    add("")
    add("> Synthetic, author-reviewed fixtures. This is not an independently")
    add("> validated benchmark, and the corpus describes a fictional product.")
    add("")

    add("## Results")
    add("")
    add(
        "| Method | Doc Recall@5 | Doc Hit@5 | MRR@10 | Abstain on no-answer | "
        "False refusals | Median ms | p95 ms |"
    )
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, summary in report["methods"].items():
        if not summary.get("available"):
            # Collapse the reason onto one line: a provider error can be several
            # lines long, and a newline inside a cell breaks the table.
            reason = " ".join(str(summary.get("reason", "unknown")).split())
            if len(reason) > 160:
                reason = reason[:157] + "..."
            add(f"| {name} | _unavailable: {reason}_ | | | | | | |")
            continue
        add(
            f"| {name} | {_fmt(summary['doc_recall_at_5'])} | "
            f"{_fmt(summary['doc_hit_at_5'])} | {_fmt(summary['mrr_at_10'])} | "
            f"{_fmt(summary['abstention_rate_unanswerable'], 2)} | "
            f"{_fmt(summary['false_refusal_rate_answerable'], 2)} | "
            f"{_fmt(summary['latency_ms_median'], 1)} | "
            f"{_fmt(summary['latency_ms_p95'], 1)} |"
        )
    add("")

    add("### How to read these numbers")
    add("")
    add(
        "- **Doc Recall@5** is the fraction of a question's labelled relevant "
        "documents found in the top 5 *documents* after deduplicating chunks. "
        "Questions labelled with several relevant documents can only reach 1.0 "
        "if all of them are retrieved, so ambiguous and version-conflict "
        "questions pull this metric down by design."
    )
    add(
        "- **Doc Hit@5** is the gentler companion: did *any* relevant document "
        "appear in the top 5."
    )
    add(
        "- **Abstain on no-answer** is the share of unanswerable questions that "
        "were correctly refused. **False refusals** is the share of answerable "
        "questions that were wrongly refused. Both come from the same "
        "content-term coverage heuristic."
    )
    add(
        "- **Latency** is wall-clock retrieval time for a single "
        f"top_k={report['settings']['serving_top_k']} query on one machine, "
        f"after {WARMUP_QUERIES} discarded warm-up queries. Embedding and index "
        "construction happen at start-up and are excluded. Treat these as "
        "indicative, not as a benchmark of the libraries involved."
    )
    add(
        "- **Citation validity** (in the JSON) checks that every cited chunk ID "
        "came from the retrieved context. It is an identifier check and says "
        "nothing about whether a claim is factually supported."
    )
    add("")
    add(
        "Semantic correctness is not scored here. Judging whether an answer is "
        "*right* would need an LLM judge or human grading; the default benchmark "
        "makes no paid calls."
    )
    add("")

    if report.get("calibration", {}).get("available"):
        calibration = report["calibration"]
        add("## Abstention calibration (development split)")
        add("")
        add(
            f"Swept on the development questions with the `{calibration['method']}` "
            "method. The configured threshold in this run was "
            f"**{calibration['configured_threshold']}**; the sweep's best balanced "
            f"accuracy was at **{calibration['selected_threshold']}**."
        )
        add("")
        add("| Threshold | Correct refusals | False refusals | Refusal recall | Answer retention | Balanced |")
        add("| --- | --- | --- | --- | --- | --- |")
        for row in calibration["sweep"]:
            add(
                f"| {row['threshold']:.2f} | {row['correct_refusals']}/{row['unanswerable_total']} | "
                f"{row['false_refusals']}/{row['answerable_total']} | "
                f"{row['refusal_recall']:.2f} | {row['answer_retention']:.2f} | "
                f"{row['balanced_accuracy']:.2f} |"
            )
        add("")

    add("## Representative failures")
    add("")
    for name, summary in report["methods"].items():
        if not summary.get("available"):
            continue
        failures = report["failures"].get(name, [])
        add(f"### {name}")
        add("")
        if not failures:
            add("No failures of the tracked kinds on this split.")
            add("")
            continue
        for failure in failures:
            add(f"- **{failure['question_id']}** ({failure['type']}) - {failure['failure']}")
            add(f"  - Question: _{failure['question']}_")
            if "expected_doc_ids" in failure:
                add(f"  - Expected: `{', '.join(failure['expected_doc_ids'])}`")
            add(f"  - Retrieved: `{', '.join(failure['retrieved_doc_ids'])}`")
            if "coverage" in failure:
                add(f"  - Term coverage: {failure['coverage']}")
        add("")

    add("## Per-question results")
    add("")
    for name, summary in report["methods"].items():
        if not summary.get("available"):
            continue
        add(f"<details><summary>{name}</summary>")
        add("")
        add("| ID | Type | Recall@5 | RR@10 | Abstained | Correct | Coverage | ms |")
        add("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for item in report["per_question"][name]:
            add(
                f"| {item['question_id']} | {item['type']} | "
                f"{_fmt(item['recall_at_5'], 2)} | {_fmt(item['reciprocal_rank_at_10'], 2)} | "
                f"{'yes' if item['abstained'] else 'no'} | "
                f"{'yes' if item['abstention_correct'] else 'NO'} | "
                f"{item['coverage']:.2f} | {item['latency_ms']:.1f} |"
            )
        add("")
        add("</details>")
        add("")

    return "\n".join(lines) + "\n"


# --- CLI ----------------------------------------------------------------------


def run_evaluation(
    split: str,
    methods: list[str],
    *,
    top_k: int,
    calibrate: bool,
    out_dir: Path,
) -> dict:
    settings = get_settings()
    db = Database(settings.db_path)

    documents, chunks = db.counts()
    if documents == 0:
        raise SystemExit(
            "The corpus is empty. Load it first:\n"
            "    python -m scripts.load_corpus"
        )

    service = RetrievalService(db, settings)
    service.ensure_index(force=True)

    questions, payload = load_questions(split)
    label_problems = validate_labels(questions, db)
    if label_problems:
        print("Label validation problems:", file=sys.stderr)
        for problem in label_problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit("Fixture labels do not match the corpus; fix them first.")

    method_summaries: dict[str, dict] = {}
    per_question: dict[str, list[dict]] = {}
    failures: dict[str, list[dict]] = {}

    for method in methods:
        print(f"  evaluating {method} ...", flush=True)
        report = evaluate_method(service, settings, questions, method, top_k=top_k)
        method_summaries[method] = report.summary()
        if report.available:
            per_question[method] = [item.to_dict() for item in report.results]
            failures[method] = representative_failures(report)
        else:
            print(f"    unavailable: {report.reason}", flush=True)

    calibration: dict = {"available": False, "reason": "not requested"}
    if calibrate:
        calibration_method = "hybrid" if "hybrid" in methods else methods[0]
        dev_questions, _ = load_questions("dev")
        calibration = calibrate_threshold(
            service, settings, dev_questions, calibration_method, top_k=top_k
        )

    report = {
        "tool": "TraceRAG",
        "split": split,
        "fixture_description": payload.get("description", ""),
        "question_count": len(questions),
        "run_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "document_count": documents,
        "chunk_count": chunks,
        "corpus_fingerprint": service.corpus_fingerprint,
        "embedding_model": settings.embedding_model,
        "settings": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "rrf_k": settings.rrf_k,
            "serving_top_k": top_k,
            "ranking_depth": RANKING_DEPTH,
            "warmup_queries": WARMUP_QUERIES,
            "abstain_coverage_threshold": settings.abstain_coverage_threshold,
            "abstain_evidence_chunks": settings.abstain_evidence_chunks,
        },
        "environment": {
            "python": f"Python {platform.python_version()}",
            "platform": platform.platform(),
        },
        "caveats": [
            "Fixtures are synthetic and author-reviewed, not independently validated.",
            "Latency comes from one machine and one process; treat it as indicative.",
            "Citation validity is an identifier check, not a factual-accuracy check.",
            "Semantic correctness of answers is not scored automatically.",
        ],
        "methods": method_summaries,
        "per_question": per_question,
        "failures": failures,
        "calibration": calibration,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "benchmark.json"
    markdown_path = out_dir / "benchmark.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"\nWrote {json_path}")
    print(f"Wrote {markdown_path}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluate",
        description="Run the TraceRAG retrieval benchmark.",
    )
    parser.add_argument(
        "--split", choices=["dev", "test"], default="test", help="Which fixture split."
    )
    parser.add_argument(
        "--methods",
        default="all",
        help="Comma-separated subset of keyword,semantic,hybrid (default: all).",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Serving top_k (default 5).")
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Also sweep the abstention threshold on the development split.",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=REPORTS_DIR, help="Where to write the report."
    )
    args = parser.parse_args(argv)

    methods = (
        list(METHODS)
        if args.methods == "all"
        else [item.strip() for item in args.methods.split(",") if item.strip()]
    )
    for method in methods:
        if method not in METHODS:
            parser.error(f"Unknown method '{method}'. Choose from {', '.join(METHODS)}.")

    print(f"TraceRAG evaluation - split={args.split}, methods={','.join(methods)}")
    report = run_evaluation(
        args.split,
        methods,
        top_k=args.top_k,
        calibrate=args.calibrate,
        out_dir=args.out_dir,
    )

    print("\nSummary:")
    for name, summary in report["methods"].items():
        if not summary.get("available"):
            print(f"  {name:9s} unavailable - {summary.get('reason')}")
            continue
        print(
            f"  {name:9s} recall@5={_fmt(summary['doc_recall_at_5'])} "
            f"hit@5={_fmt(summary['doc_hit_at_5'])} "
            f"mrr@10={_fmt(summary['mrr_at_10'])} "
            f"abstain={_fmt(summary['abstention_rate_unanswerable'], 2)} "
            f"median={_fmt(summary['latency_ms_median'], 1)}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
