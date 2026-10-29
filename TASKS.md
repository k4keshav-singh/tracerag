# TASKS

Progress log for the TraceRAG build. Everything marked done was built **and
run**; nothing below is aspirational.

## Completed

### Foundation
- [x] Project scaffold, virtualenv, dependency manifest (`requirements.txt`,
      `requirements-dev.txt`) and a resolved lock file (`requirements.lock.txt`)
- [x] Environment-driven settings (`app/config.py`) via pydantic-settings
- [x] SQLite schema and persistence layer (`app/db.py`): documents, chunks,
      index metadata
- [x] FastAPI application with lifespan-managed index build

### Corpus
- [x] 18 synthetic NimbusDesk Markdown documents covering installation,
      configuration, workspaces, roles, API auth, rate limits, pagination,
      webhooks, retries, retention, exports, troubleshooting, SSO/SCIM, CLI,
      release notes and migration
- [x] Stable document IDs with version/status frontmatter; every document
      labelled synthetic
- [x] Explicitly superseded document (`nd-auth-legacy-006`) with its current
      replacement (`nd-auth-005`), including a deliberate factual contradiction
      about token expiry
- [x] Overlapping terminology across documents ("token" appears as bearer
      token, workspace token and rate-limiter token bucket) so retrieval is
      non-trivial
- [x] Idempotent loader: `python -m scripts.load_corpus`

### Ingestion
- [x] Markdown-aware, line-aligned chunking with configurable size/overlap
- [x] Source metadata per chunk: heading, start line, end line, filename
- [x] Frontmatter parser (flat key/value, no YAML dependency)
- [x] Content-hash deduplication; stable `{doc_id}::{ordinal:04d}` chunk IDs
- [x] Upload validation: 1 MiB cap, UTF-8 only, `.md`/`.txt` only, NUL rejection
- [x] Filename sanitisation (path traversal flattened, unsafe characters stripped)
- [x] Index rebuild driven by a corpus fingerprint over content + chunking +
      embedding model
- [x] `rechunk_all` rebuilds chunks from stored raw text when chunking changes

### Retrieval
- [x] Okapi BM25 written out (`app/retrieval/bm25.py`), not imported
- [x] Semantic retrieval: sentence-transformers + NumPy cosine, no vector DB
- [x] Disk-cached embedding matrix keyed by corpus fingerprint
- [x] Reciprocal rank fusion (`app/retrieval/fusion.py`), pure function
- [x] Unified result shape with per-method `score_semantics` explaining that
      scores are not interchangeable
- [x] Honest degradation: semantic/hybrid report unavailable with a reason and
      return HTTP 503 rather than silently serving BM25

### Answering
- [x] Extractive mode (default, no key) with deterministic sentence selection
- [x] Abstention heuristic: content-term coverage, with per-term explanation
- [x] Threshold calibrated by sweep on the dev split only → 0.55
- [x] LLM adapter for any OpenAI-compatible `/chat/completions`
- [x] Structured output contract `{answer, cited_chunk_ids, insufficient_evidence}`
- [x] Server-side citation-ID validation; all-invalid answers rejected
- [x] Prompt treats passages as untrusted, fenced data
- [x] Clearly labelled extractive fallback on provider failure
- [x] Credentials server-side only; never in responses, payload or logs

### Frontend
- [x] Visual language rebuilt against a published design reference (credited in
      the README): DM Sans, the four-colour palette, lavender ground with a
      drifting gradient mesh, label-over-value control fields, violet pill CTA
- [x] Light and dark themes with a header toggle, remembered in localStorage,
      defaulting to `prefers-color-scheme`
- [x] Motion that carries meaning: animated coverage meter with a threshold
      tick, per-result score bars scaled within one query, staggered result
      entry, count-up stats, scroll reveal, scroll-progress bar
- [x] Drag-and-drop upload, toast notifications, shimmer loading skeletons
- [x] Full `prefers-reduced-motion` support
- [x] Asset cache-busting (`?v=`) so a redeploy is never served stale
- [x] Responsive single-page UI, no build step
- [x] Question field, example chips (answerable / absent / outdated / paraphrase
      / careful-retrieval), method and mode selectors, top-K
- [x] Answer panel with explicit mode banner
- [x] Clickable citations opening the supporting passage with its line range
- [x] Retrieved-chunk inspection with rank, score, status badges, expand/collapse
- [x] Document list with version/status badges; upload control
- [x] Benchmark table rendered from the checked-in report
- [x] Loading, empty and error states throughout
- [x] All document-derived text escaped; no document HTML injected

### Evaluation
- [x] 20 development questions, 20 held-out test questions
- [x] Mix of answerable, paraphrase, ambiguous, version-conflict and
      unanswerable questions, with labelled relevant documents and reference facts
- [x] Label validation against the corpus (the CLI refuses to run on bad labels)
- [x] Evaluation CLI writing JSON + Markdown
- [x] Doc-level Recall@5 (deduplicated by document), Doc Hit@5, MRR@10
- [x] Latency with warm-up excluded and conditions recorded
- [x] Abstention behaviour and false-refusal rate
- [x] Per-question results and representative failures
- [x] Abstention threshold calibration sweep (dev split only)
- [x] Records corpus fingerprint, model, settings, environment, timestamp
- [x] Unavailable methods reported explicitly rather than omitted

### Tests and verification
- [x] 99 tests, all passing (`pytest -q`)
- [x] Chunk overlap and source metadata
- [x] Duplicate ingestion; persistence across a simulated restart
- [x] Retrieval of known corpus facts
- [x] RRF correctness against the formula
- [x] Rejection of invented citation IDs
- [x] Oversized, unsupported, non-UTF-8 uploads and unsafe filenames
- [x] Provider failures via `httpx.MockTransport` (HTTP error, network error,
      malformed JSON, fenced JSON)
- [x] Irrelevant question yields no unsupported generated answer
- [x] Adversarial document fixture with embedded "ignore the user" instructions
- [x] HTTP smoke test covering sample loading, listing, retrieval, answering,
      citation resolution, abstention and upload rejection
- [x] Browser verification of the main UI flow with a captured screenshot

### Packaging and documentation
- [x] `README.md` with problem, features, honest status, tested setup, no-key
      demo, LLM config, Mermaid diagram, real benchmark results and their
      limitations, known failures, resource requirements, résumé bullets and a
      provenance section
- [x] `TASKS.md` (this file)
- [x] `.env.example`, `.gitignore`, `.dockerignore`
- [x] `Dockerfile` (CPU torch, non-root, healthcheck) and `docker-compose.yml`
- [x] `.github/workflows/ci.yml`
- [x] `docs/architecture.md`, `docs/design-decisions.md`, `docs/demo-script.md`
- [x] `reports/benchmark.{json,md}` from a real run

## Bugs found and fixed during the build

These were caught by running things, not by reading them:

1. **30-second first query.** The embedding model loaded lazily on first search
   rather than at start-up, because a cache hit returned before `_load_model()`.
   Moved the load to the top of `build()`. Median semantic latency went from
   ~30,000 ms on the first query to ~23 ms.
2. **Semantic reported available with no model.** With an empty corpus, `build()`
   returned early before loading the model, so `/api/status` claimed semantic
   worked when it could not serve a query. Caught by `test_api.py`. Moved the
   model load above the empty-corpus early return.
3. **Abstention threshold too low.** The initial guess of 0.50 answered
   "What is NimbusDesk's phone support number?" instead of refusing it. The dev
   sweep showed 0.50 catches 1/3 unanswerable questions and 0.55 catches 3/3.
   Recalibrated to 0.55.
4. **Passage dialog visible on page load.** `.dialog-backdrop { display: flex }`
   overrode the `hidden` attribute, so the modal covered the page and blocked
   the form. Found in the browser, not in tests. Added
   `.dialog-backdrop[hidden] { display: none }`.
5. **Markdown headings selected as evidence.** Sentence selection scored
   `# Webhook Delivery and Retries` highly because it shares the question's
   vocabulary. Filtered headings, table rows and bold-only lines.
6. **Docker build failed on `chown`.** With `BAKE_MODEL=false`, `/opt/hf-cache`
   was never created, so `chown` failed. Added an explicit `mkdir -p`.
7. **Unescaped filename in the frontend.** Filenames are sanitised server-side,
   but were interpolated into `innerHTML` without escaping. Escaped at the sink
   too.
8. **Question field rendered 200px tall on load.** The auto-grow routine measured
   `scrollHeight` before stylesheets and webfonts had settled, read a bogus
   value and clamped it to its own maximum. Deferred the first measurement to
   the next frame, repeated it on `window.load`, and added CSS `min-height` /
   `max-height` so the field is sane even before the script runs. That was not
   enough - it still opened at its maximum - so the measurement was removed
   from the load path entirely: the empty field is sized by CSS alone, and the
   script only resizes in response to typing. Scripting only what CSS cannot do
   made the load path deterministic.
9. **Saturated palette read as a mock-up.** Full-chroma accents, coloured glow
   shadows and an iridescent gradient border on the query panel made the UI
   look rendered rather than real. Moved to a desaturated pastel palette with
   neutral shadows, and verified all twenty colour pairs against WCAG AA with a
   contrast script rather than by eye (six values failed the first pass and
   were corrected).

## Unresolved limitations

Carried deliberately, with reasons:

- **Hybrid does not beat keyword on this corpus.** Reported as-is in the README
  and benchmark rather than reframed. Small corpus with consistent terminology
  favours BM25.
- **Abstention is lexical only.** It cannot detect passages that contain every
  query term yet answer a different question. It wrongly refuses `test-012` on
  all three methods.
- **The 0.55 threshold is corpus-specific** and would need recalibration
  elsewhere.
- **LLM mode has never run against a live provider.** Mocks cover the failure
  surface; no paid call was made, by design.
- **Semantic correctness is not scored.** Would require an LLM judge or human
  grading. Citation validity is reported instead, explicitly labelled as an
  identifier check.
- **Prompt injection is only partly defensible.** Deterministic guarantees are
  tested; model obedience is not guaranteed by prompt wording.
- **20 questions per split** is small enough that few-point differences are
  noise.
- **Chunk size is in characters, not tokens**, so dense chunks may exceed the
  256-token embedding window.
- **No reranker.** Likely the biggest available quality win, deliberately out of
  scope.
- **No authentication**; anyone who can reach the port can upload.
- **CI has now run.** All four jobs (tests on Python 3.11 and 3.12, the HTTP
  smoke test, and the Docker build) passed on the first execution. The
  evaluation run in CI reproduced every quality metric from
  `reports/benchmark.json` exactly, on different hardware, OS and Python patch
  version — which is the strongest evidence so far that the benchmark is
  genuinely reproducible. Latency differs, as expected.

## Out of scope (not attempted)

PDF parsing, URL ingestion, multi-corpus support, user accounts, a vector
database, agent frameworks, and streaming responses.
