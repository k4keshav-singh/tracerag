# TraceRAG retrieval benchmark

- **Split:** `test` (20 questions)
- **Run:** 2026-10-29T10:00:19+00:00
- **Corpus:** 18 documents, 53 chunks
- **Corpus fingerprint:** `5a2a77f50c8c22a56967f87022450dca031700aa7863f6bbacb413e6e2957360`
- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2`
- **Retrieval settings:** chunk_size=900, chunk_overlap=180, rrf_k=60, serving_top_k=5, ranking_depth=30
- **Abstention threshold:** 0.55 (content-term coverage)
- **Environment:** Python 3.12.10 on Windows-11-10.0.26200-SP0

> Synthetic, author-reviewed fixtures. This is not an independently
> validated benchmark, and the corpus describes a fictional product.

## Results

| Method | Doc Recall@5 | Doc Hit@5 | MRR@10 | Abstain on no-answer | False refusals | Median ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| keyword | 0.971 | 1.000 | 0.971 | 1.00 | 0.06 | 1.3 | 1.7 |
| semantic | 0.912 | 1.000 | 0.894 | 1.00 | 0.18 | 28.2 | 37.6 |
| hybrid | 0.941 | 1.000 | 0.971 | 1.00 | 0.06 | 26.8 | 31.0 |

### How to read these numbers

- **Doc Recall@5** is the fraction of a question's labelled relevant documents found in the top 5 *documents* after deduplicating chunks. Questions labelled with several relevant documents can only reach 1.0 if all of them are retrieved, so ambiguous and version-conflict questions pull this metric down by design.
- **Doc Hit@5** is the gentler companion: did *any* relevant document appear in the top 5.
- **Abstain on no-answer** is the share of unanswerable questions that were correctly refused. **False refusals** is the share of answerable questions that were wrongly refused. Both come from the same content-term coverage heuristic.
- **Latency** is wall-clock retrieval time for a single top_k=5 query on one machine, after 3 discarded warm-up queries. Embedding and index construction happen at start-up and are excluded. Treat these as indicative, not as a benchmark of the libraries involved.
- **Citation validity** (in the JSON) checks that every cited chunk ID came from the retrieved context. It is an identifier check and says nothing about whether a claim is factually supported.

Semantic correctness is not scored here. Judging whether an answer is *right* would need an LLM judge or human grading; the default benchmark makes no paid calls.

## Abstention calibration (development split)

Swept on the development questions with the `hybrid` method. The configured threshold in this run was **0.55**; the sweep's best balanced accuracy was at **0.55**.

| Threshold | Correct refusals | False refusals | Refusal recall | Answer retention | Balanced |
| --- | --- | --- | --- | --- | --- |
| 0.00 | 0/3 | 0/17 | 0.00 | 1.00 | 0.50 |
| 0.05 | 0/3 | 0/17 | 0.00 | 1.00 | 0.50 |
| 0.10 | 0/3 | 0/17 | 0.00 | 1.00 | 0.50 |
| 0.15 | 0/3 | 0/17 | 0.00 | 1.00 | 0.50 |
| 0.20 | 0/3 | 0/17 | 0.00 | 1.00 | 0.50 |
| 0.25 | 0/3 | 0/17 | 0.00 | 1.00 | 0.50 |
| 0.30 | 1/3 | 0/17 | 0.33 | 1.00 | 0.67 |
| 0.35 | 1/3 | 0/17 | 0.33 | 1.00 | 0.67 |
| 0.40 | 1/3 | 0/17 | 0.33 | 1.00 | 0.67 |
| 0.45 | 1/3 | 0/17 | 0.33 | 1.00 | 0.67 |
| 0.50 | 1/3 | 0/17 | 0.33 | 1.00 | 0.67 |
| 0.55 | 3/3 | 1/17 | 1.00 | 0.94 | 0.97 |
| 0.60 | 3/3 | 1/17 | 1.00 | 0.94 | 0.97 |
| 0.65 | 3/3 | 2/17 | 1.00 | 0.88 | 0.94 |
| 0.70 | 3/3 | 3/17 | 1.00 | 0.82 | 0.91 |
| 0.75 | 3/3 | 3/17 | 1.00 | 0.82 | 0.91 |
| 0.80 | 3/3 | 3/17 | 1.00 | 0.82 | 0.91 |
| 0.85 | 3/3 | 5/17 | 1.00 | 0.71 | 0.85 |
| 0.90 | 3/3 | 9/17 | 1.00 | 0.47 | 0.74 |
| 0.95 | 3/3 | 9/17 | 1.00 | 0.47 | 0.74 |
| 1.00 | 3/3 | 9/17 | 1.00 | 0.47 | 0.74 |

## Representative failures

### keyword

- **test-012** (paraphrase) - refused an answerable question
  - Question: _My export download link stopped working after an hour. Is the export gone?_
  - Expected: `nd-exports-012`
  - Retrieved: `nd-exports-012, nd-cli-018, nd-retention-011, nd-webhooks-009, nd-ratelimits-007`
  - Term coverage: 0.5
- **test-017** (ambiguous) - only part of the labelled relevant set was retrieved
  - Question: _What is the maximum number of keys?_
  - Expected: `nd-workspaces-003, nd-auth-005`
  - Retrieved: `nd-auth-005, nd-changelog-015, nd-troubleshoot-api-014, nd-pagination-008, nd-migration-016`

### semantic

- **test-004** (answerable) - refused an answerable question
  - Question: _How large can a single export part be?_
  - Expected: `nd-exports-012`
  - Retrieved: `nd-exports-012, nd-ratelimits-007, nd-changelog-015, nd-cli-018, nd-retention-011`
  - Term coverage: 0.5
- **test-011** (paraphrase) - refused an answerable question
  - Question: _If I rename a workspace, do links using the old name break straight away?_
  - Expected: `nd-workspaces-003`
  - Retrieved: `nd-workspaces-003, nd-retention-011, nd-auth-005, nd-auth-legacy-006, nd-migration-016`
  - Term coverage: 0.444
- **test-012** (paraphrase) - refused an answerable question
  - Question: _My export download link stopped working after an hour. Is the export gone?_
  - Expected: `nd-exports-012`
  - Retrieved: `nd-exports-012, nd-cli-018, nd-changelog-015, nd-retention-011, nd-troubleshoot-install-013`
  - Term coverage: 0.5
- **test-014** (version_conflict) - only part of the labelled relevant set was retrieved
  - Question: _How many webhook retries did NimbusDesk do before release 2.4?_
  - Expected: `nd-changelog-015, nd-migration-016`
  - Retrieved: `nd-cli-018, nd-webhook-retries-010, nd-webhooks-009, nd-config-002, nd-changelog-015`

### hybrid

- **test-012** (paraphrase) - refused an answerable question
  - Question: _My export download link stopped working after an hour. Is the export gone?_
  - Expected: `nd-exports-012`
  - Retrieved: `nd-exports-012, nd-cli-018, nd-retention-011, nd-webhooks-009, nd-changelog-015`
  - Term coverage: 0.5
- **test-014** (version_conflict) - only part of the labelled relevant set was retrieved
  - Question: _How many webhook retries did NimbusDesk do before release 2.4?_
  - Expected: `nd-changelog-015, nd-migration-016`
  - Retrieved: `nd-changelog-015, nd-webhook-retries-010, nd-webhooks-009, nd-install-001, nd-auth-005`
- **test-017** (ambiguous) - only part of the labelled relevant set was retrieved
  - Question: _What is the maximum number of keys?_
  - Expected: `nd-workspaces-003, nd-auth-005`
  - Retrieved: `nd-auth-005, nd-changelog-015, nd-roles-004, nd-migration-016, nd-troubleshoot-api-014`

## Per-question results

<details><summary>keyword</summary>

| ID | Type | Recall@5 | RR@10 | Abstained | Correct | Coverage | ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| test-001 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 1.1 |
| test-002 | answerable | 1.00 | 1.00 | no | yes | 0.78 | 1.7 |
| test-003 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 1.1 |
| test-004 | answerable | 1.00 | 1.00 | no | yes | 0.75 | 1.3 |
| test-005 | answerable | 1.00 | 1.00 | no | yes | 0.80 | 1.4 |
| test-006 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 1.2 |
| test-007 | answerable | 1.00 | 1.00 | no | yes | 0.80 | 1.3 |
| test-008 | answerable | 1.00 | 1.00 | no | yes | 0.75 | 1.1 |
| test-009 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 1.8 |
| test-010 | answerable | 1.00 | 1.00 | no | yes | 0.86 | 1.3 |
| test-011 | paraphrase | 1.00 | 1.00 | no | yes | 0.67 | 1.5 |
| test-012 | paraphrase | 1.00 | 1.00 | yes | NO | 0.50 | 1.3 |
| test-013 | paraphrase | 1.00 | 1.00 | no | yes | 0.86 | 1.5 |
| test-014 | version_conflict | 1.00 | 1.00 | no | yes | 0.83 | 1.6 |
| test-015 | version_conflict | 1.00 | 1.00 | no | yes | 0.86 | 1.3 |
| test-016 | ambiguous | 1.00 | 0.50 | no | yes | 1.00 | 1.2 |
| test-017 | ambiguous | 0.50 | 1.00 | no | yes | 0.67 | 1.1 |
| test-018 | unanswerable | n/a | n/a | yes | yes | 0.20 | 1.2 |
| test-019 | unanswerable | n/a | n/a | yes | yes | 0.25 | 1.2 |
| test-020 | unanswerable | n/a | n/a | yes | yes | 0.25 | 1.3 |

</details>

<details><summary>semantic</summary>

| ID | Type | Recall@5 | RR@10 | Abstained | Correct | Coverage | ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| test-001 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 32.1 |
| test-002 | answerable | 1.00 | 1.00 | no | yes | 0.78 | 37.6 |
| test-003 | answerable | 1.00 | 1.00 | no | yes | 0.86 | 38.3 |
| test-004 | answerable | 1.00 | 1.00 | yes | NO | 0.50 | 33.9 |
| test-005 | answerable | 1.00 | 1.00 | no | yes | 0.60 | 30.5 |
| test-006 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 31.6 |
| test-007 | answerable | 1.00 | 1.00 | no | yes | 0.60 | 28.2 |
| test-008 | answerable | 1.00 | 1.00 | no | yes | 0.62 | 24.0 |
| test-009 | answerable | 1.00 | 0.50 | no | yes | 1.00 | 22.4 |
| test-010 | answerable | 1.00 | 1.00 | no | yes | 0.86 | 32.6 |
| test-011 | paraphrase | 1.00 | 1.00 | yes | NO | 0.44 | 30.6 |
| test-012 | paraphrase | 1.00 | 1.00 | yes | NO | 0.50 | 21.8 |
| test-013 | paraphrase | 1.00 | 1.00 | no | yes | 0.71 | 30.8 |
| test-014 | version_conflict | 0.50 | 0.20 | no | yes | 0.67 | 21.3 |
| test-015 | version_conflict | 0.50 | 1.00 | no | yes | 0.71 | 17.7 |
| test-016 | ambiguous | 1.00 | 0.50 | no | yes | 1.00 | 17.1 |
| test-017 | ambiguous | 0.50 | 1.00 | no | yes | 0.67 | 20.3 |
| test-018 | unanswerable | n/a | n/a | yes | yes | 0.20 | 28.2 |
| test-019 | unanswerable | n/a | n/a | yes | yes | 0.25 | 20.7 |
| test-020 | unanswerable | n/a | n/a | yes | yes | 0.25 | 27.5 |

</details>

<details><summary>hybrid</summary>

| ID | Type | Recall@5 | RR@10 | Abstained | Correct | Coverage | ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| test-001 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 31.4 |
| test-002 | answerable | 1.00 | 1.00 | no | yes | 0.78 | 31.0 |
| test-003 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 29.1 |
| test-004 | answerable | 1.00 | 1.00 | no | yes | 0.75 | 28.3 |
| test-005 | answerable | 1.00 | 1.00 | no | yes | 0.60 | 26.9 |
| test-006 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 18.3 |
| test-007 | answerable | 1.00 | 1.00 | no | yes | 0.80 | 26.5 |
| test-008 | answerable | 1.00 | 1.00 | no | yes | 0.62 | 26.2 |
| test-009 | answerable | 1.00 | 1.00 | no | yes | 1.00 | 23.8 |
| test-010 | answerable | 1.00 | 1.00 | no | yes | 0.86 | 27.6 |
| test-011 | paraphrase | 1.00 | 1.00 | no | yes | 0.56 | 26.7 |
| test-012 | paraphrase | 1.00 | 1.00 | yes | NO | 0.50 | 30.1 |
| test-013 | paraphrase | 1.00 | 1.00 | no | yes | 0.71 | 26.9 |
| test-014 | version_conflict | 0.50 | 1.00 | no | yes | 0.83 | 26.6 |
| test-015 | version_conflict | 1.00 | 1.00 | no | yes | 0.86 | 26.8 |
| test-016 | ambiguous | 1.00 | 0.50 | no | yes | 1.00 | 27.8 |
| test-017 | ambiguous | 0.50 | 1.00 | no | yes | 0.67 | 26.2 |
| test-018 | unanswerable | n/a | n/a | yes | yes | 0.20 | 26.0 |
| test-019 | unanswerable | n/a | n/a | yes | yes | 0.25 | 25.6 |
| test-020 | unanswerable | n/a | n/a | yes | yes | 0.25 | 27.4 |

</details>

