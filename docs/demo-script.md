# Demo script

## The two-minute version

Assumes the server is running at <http://localhost:8000> with the sample corpus
loaded. Setup is in the README.

### 0:00 — What it is (15s)

> TraceRAG answers questions over a document corpus and shows you the evidence
> behind every answer. It runs three retrieval methods side by side — keyword,
> semantic, and a hybrid of the two — and it benchmarks them against a
> checked-in question set, so the retrieval claims are measured rather than
> asserted.

Point at the header strip: **18 docs / 53 chunks**, three methods green,
**extractive only** — no API key is configured, and the app says so.

### 0:15 — An answer with evidence (35s)

Click the **Answerable** example chip: *"How long do API keys last before they
expire?"* → **Ask**.

Three things to point out, in order:

1. **The banner.** "Extracted evidence — passages selected from the corpus, not
   generated reasoning. No language model wrote this text." The mode is never
   ambiguous.
2. **The citations.** Click one. A dialog opens with the exact passage, the
   source filename, and the line range — `nd-auth-005.md` lines 30–50. The
   citation is verifiable, not decorative.
3. **Retrieved passages below.** Every chunk that was considered, with its rank,
   score, and document status badge.

### 0:50 — Declining to answer (25s)

Click the **Not in the corpus** chip: *"What is NimbusDesk's phone support
number?"* → **Ask**.

> It refuses, and it explains why rather than just shrugging.

Expand **"Why this was or was not answered"**. The question's terms are listed,
green for found, red for not found. The heuristic is content-term coverage, and
the threshold was calibrated on a development split — the panel says so.

> This is the part most RAG demos skip. A system that always answers is easy.

### 1:15 — Version conflict (20s)

Click the **Version conflict** chip: *"Do workspace tokens expire?"* → **Ask**.

In the retrieved passages, point at the two status badges: `nd-auth-005` is
**CURRENT**, `nd-auth-legacy-006` is **SUPERSEDED** and the sidebar shows
"replaced by nd-auth-005".

> The corpus deliberately contains a superseded page that contradicts the
> current one. Retrieval surfaces both, and the provenance is visible, so you
> can see the conflict instead of being silently handed the stale answer.

### 1:35 — The benchmark (25s)

Scroll to **Benchmark**.

> Twenty held-out test questions, run across all three methods. Document-level
> Recall@5, MRR@10, abstention rate on unanswerable questions, and latency.

Say the honest headline out loud:

> On this corpus hybrid does **not** beat keyword. BM25 gets Recall@5 of 0.971
> against hybrid's 0.941, and they tie on MRR@10. The corpus is small and
> uses consistent terminology, which is exactly where lexical search is
> strong. I report that rather than picking the framing where hybrid wins.

Close:

> Everything here runs with no API key. LLM mode is wired up and tested against
> mocks, but the default demo needs nothing paid.

## Longer walkthrough

### Compare retrieval methods on one question

Use *"What is the largest page size a list endpoint will return?"* — the
paraphrase chip. The corpus never says "page size"; it says "the maximum
accepted value is 200".

Run it three times, switching **Retrieval method**:

- **Keyword** — matches on "list", "endpoint", "return".
- **Semantic** — matches the paraphrase through meaning.
- **Hybrid** — fuses both rankings.

Point at the score column each time and at the `score_semantics` line above the
passages: BM25 scores are unbounded, cosine is in [-1, 1], RRF is a sum of
1/(k+rank). They are not interchangeable, and the UI says so rather than
inviting the comparison.

### Upload and deduplication

Upload any `.md` or `.txt` file in the sidebar. Then upload the same file again
under a different name — it is recognised by content hash and reported as a
duplicate rather than ingested twice.

Try `notes.pdf` — rejected, unsupported type. Try a file over 1 MB — rejected,
with the limit stated.

### Run the benchmark live

```bash
python -m app.evaluate --split test --calibrate
```

Open `reports/benchmark.md`. Show the per-question tables and the
**Representative failures** section — including `test-012`, which all three
methods wrongly refuse. Then the **Abstention calibration** sweep, and note the
configured threshold came from the dev split only.

### Show degradation

```bash
EMBEDDING_MODEL=definitely/not-a-real-model python -m uvicorn app.main:app --port 8001
```

Open <http://localhost:8001>. Keyword is green; semantic and hybrid are marked
off with the load error as the reason, and the method dropdown disables them.
The app does not silently serve BM25 results labelled "hybrid".

## Questions to expect

**"Why doesn't hybrid win?"**
Small corpus, consistent vocabulary, and questions that mostly share terms with
the documents — ideal conditions for BM25. Hybrid's value shows on the
paraphrase questions, where semantic retrieval carries it; averaged over 20
questions that advantage does not outweigh BM25's precision on the rest. With
20 questions, differences of a few points are within noise, which the report
states.

**"Is the citation check proof the answer is right?"**
No, and the report is explicit about it. It proves a cited ID was in the
retrieved context. A model can cite a real chunk for a claim that chunk does not
support. Checking that would need an LLM judge or human grading.

**"Can prompt injection get through?"**
The deterministic parts are tested: injected text stays inside a passage
boundary, and a fabricated citation ID is rejected. Whether a model *obeys* an
injected instruction is not something prompt wording can guarantee, and the
project does not claim it.

**"Why no vector database?"**
53 chunks. The embedding matrix is 81 KB and search is one NumPy mat-vec. A
vector DB would add a dependency and a network hop for no measurable gain. It
would be the right call somewhere past ~10⁵ chunks.
