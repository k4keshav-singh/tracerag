# Design decisions

The choices worth defending, and what each one costs.

## BM25 written out instead of a library

`rank_bm25` would have been three lines. Writing Okapi BM25 out is ~90 lines in
`app/retrieval/bm25.py`.

The reason is that retrieval quality is the point of this project, and a
scoring function I cannot inspect is one I cannot debug or explain. It is also
directly unit-testable: `test_bm25_ranks_the_matching_document_first` asserts
ranking behaviour, not that a dependency was called.

**Cost:** one more thing to get wrong. Mitigated by tests that pin the formula's
observable behaviour, and by the standard k1=1.5 / b=0.75 parameterisation.

## Rank fusion, not score fusion

BM25 scores are unbounded and corpus-dependent. Cosine similarities sit in
[-1, 1]. Combining them numerically requires normalising first, and every
normalisation (min-max over the result set, z-score, softmax) is a tuning
decision that changes results and has to be justified separately.

Reciprocal rank fusion uses only positions, so the question never arises. The
API reports `score_semantics` per method, and the UI prints it, so nobody reads
an RRF score of 0.032 as "3% relevant".

**Cost:** RRF discards magnitude. A result that BM25 scores far above everything
else contributes exactly what a narrow first place contributes. On this corpus
that has not hurt — see the benchmark — but on a corpus with a few very strong
lexical signals it might.

One tuning note: hybrid fuses deeper lists (depth 40) than it returns (top 5).
RRF's value is promoting items both rankers like; if each input list were only
5 long, an item ranked 7th by both would be invisible.

## Chunking by line, not by token

Chunks are built from whole lines, with `chunk_size` measured in **characters**.

Characters are the unit the chunker actually controls. Reporting a token count
would mean reporting a number produced by a tokeniser the chunker does not use.
Line alignment is what makes `start_line`/`end_line` exact, and an exact line
range is what makes a citation verifiable rather than decorative.

**Cost:** chunks are not uniform in tokens, so a chunk of dense table rows
carries more tokens than a chunk of prose at the same character count. For
embedding with a 256-token model this is a real limitation: a very dense 900
character chunk may be truncated by the model.

## Abstention by content-term coverage

The question this had to answer: what single signal works across BM25, cosine
and RRF, whose scores are not comparable?

A cosine floor only works for semantic. A BM25 floor only works for keyword.
Neither has any meaning for RRF. So the signal is **lexical coverage**: the
fraction of the question's content-bearing terms (length ≥ 3, stopwords removed)
that appear anywhere in the top 5 retrieved passages. One threshold then works
for all three methods, and it is explainable to a user — the UI shows exactly
which terms were and were not found.

**Calibration.** The threshold was swept on the **20 development questions
only**, with hybrid retrieval:

| Threshold | Correct refusals | False refusals | Balanced accuracy |
| --- | --- | --- | --- |
| 0.50 | 1/3 | 0/17 | 0.67 |
| **0.55** | **3/3** | **1/17** | **0.97** |
| 0.65 | 3/3 | 2/17 | 0.94 |
| 0.85 | 3/3 | 5/17 | 0.85 |
| 1.00 | 3/3 | 9/17 | 0.74 |

0.55 is the knee. Reproduce it with
`python -m app.evaluate --split dev --calibrate`. Nothing was tuned against the
held-out test split.

**This is a calibrated value for this corpus, not a universal threshold.** It
depends on how questions are phrased relative to the documents. A corpus whose
documents and questions share less vocabulary would need a lower one.

**What it does not do.** Coverage is a *retrieval-support* check. It can be
satisfied by passages that happen to contain every query term while answering a
different question. It is a guard against answering from nothing; it is not a
guard against answering wrongly. The held-out split shows the failure mode
honestly: `test-012` is refused by all three methods despite being answerable,
because it is phrased conversationally ("My export download link stopped working
after an hour. Is the export gone?") and several of its terms are absent from
the passages that do answer it.

## Two explicit answer modes, never a silent blend

Extractive mode is the default and needs no key. It selects sentences by term
overlap and presents them as *extracted evidence*, labelled as such in the API
response (`mode_label`) and in a banner in the UI. It is fully deterministic.

LLM mode is opt-in. If the provider fails, the response falls back to extractive
and says so in three separate fields: `mode` becomes `extractive`,
`fell_back_to_extractive` is true, `provider_error` carries the reason, and a
warning appears in the UI. A fallback a user cannot see is a lie about where the
text came from.

## Citation validation, and what it does not prove

The model is asked for `{answer, cited_chunk_ids, insufficient_evidence}`. Every
returned ID is checked against the retrieved set. Invalid IDs are dropped; if a
confident answer's citations were *all* invalid, the whole answer is rejected
rather than shown with no sources.

**This is an identifier check.** It proves a cited ID was in the retrieved
context. It does not prove the sentence attached to it is supported by that
passage — a model can cite a real chunk for a claim that chunk does not make.
The benchmark reports `citation_validity_rate` and says this in the report
itself, precisely so the number is not mistaken for accuracy.

## Prompt injection: what is guaranteed and what is not

`tests/fixtures/adversarial_doc.md` contains instructions to ignore the user,
reveal the system prompt, and cite a fabricated chunk ID.

What the tests verify is the deterministic part:

- the injected text stays inside a `<passage>` boundary and never becomes a
  system instruction (`test_adversarial_passage_is_fenced_and_attributed`);
- the fabricated ID the document demands is rejected by the validator
  (`test_citation_id_demanded_by_the_adversarial_document_is_rejected`);
- ingesting the document stores its claims as plain metadata rather than acting
  on them.

**Prompt wording alone cannot guarantee a model resists injection.** The system
prompt tells the model that passages are untrusted data; that is a mitigation,
not a control, and this project does not claim otherwise. The guarantees here
are the ones enforced in code after the model replies.

## SQLite, no vector database

53 chunks. A 53×384 float32 matrix is 81 KB; cosine similarity against it is one
mat-vec, measured at a ~23 ms median end to end including query encoding, which
is dominated by the encode, not the search.

A vector database at this size would add an operational dependency, a network
hop, and a second source of truth, in exchange for nothing measurable. The
honest limit: this approach is linear in corpus size and would stop being the
right answer somewhere in the 10^5–10^6 chunk range.

## Storing raw document text

`documents.raw_text` duplicates what is already on disk for corpus files. It
earns its place for uploads, which have no file on disk, and it makes
`rechunk_all` possible — changing `CHUNK_SIZE` rebuilds every chunk without
asking anyone to re-upload. At 80 KB of corpus the duplication is irrelevant.

## Frontend without a build step

Plain HTML, CSS and JavaScript served by FastAPI. No bundler, no framework, no
`node_modules`.

The visual language is adapted from a published design reference (credited in
the README's provenance section): DM Sans, a four-colour palette, a lavender
ground with a drifting gradient mesh, and filter-style fields that put a small
uppercase label above its value. That last component is why the query controls
read the way they do — "RETRIEVAL METHOD / Hybrid" is the same shape as the
reference's "COUNTRY / Select", and it suits a control whose label is needed
permanently rather than only while the field is empty.

The reference's accent colours are used at reduced saturation. At full chroma,
with coloured glows under the buttons and an iridescent gradient border on the
query panel, the page read as a mock-up rather than as software: saturated
accents plus halo shadows are the two cues that make an interface look
rendered. The hues are kept and the chroma pulled back - chalky lavender and
lilac for accents, desaturated sage, ochre and clay for status, soft charcoal
instead of near-black for text, and neutral shallow shadows instead of coloured
halos. The gradient border was removed outright.

Every colour pair was checked rather than eyeballed. The palette passes WCAG AA
on all twenty foreground/background combinations it actually uses: 4.5:1 for
body and small text, 3:1 for the large hero type. Pastel accents are kept out of
small text - `--violet` is for fills and gradients, `--violet-deep` is the
text-safe variant, and `--primary-deep` carries small text on tinted fills.

Motion is used where it carries information, not as decoration: the coverage
meter animates to the measured value against a tick mark at the abstention
threshold, score bars are scaled within a single result set (never across
methods, whose scores are not comparable), and results stagger in so the eye
can follow rank order. Everything decorative is disabled under
`prefers-reduced-motion`, where the count-up animation snaps to its final value
rather than being skipped entirely.

The UI needs a form, a result list, a modal and four fetch calls. React plus a
build pipeline would add a toolchain to install, a build step to CI, and a
second language ecosystem to the Dockerfile, to produce the same page. The
constraint this imposes is real — all document text is escaped through one
helper (`esc`) and inserted via `innerHTML` templates rather than a framework's
automatic escaping — so that helper is the single place XSS could enter, and it
is used on every document-derived value.

## Latency measurement

Reported latency excludes index construction and model loading, both of which
happen at start-up, and discards three warm-up queries per method. It is wall
clock for a single `top_k=5` query, on one machine, in one process.

That is the number a user waits on. It is **not** a benchmark of BM25 versus
embeddings as implementations, and the report says so. Keyword at ~0.7 ms versus
semantic at ~23 ms mostly measures "no neural network" versus "one forward pass
to encode the query".
