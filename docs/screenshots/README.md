# Screenshots

Captured from a real run of TraceRAG in a browser on 2026-10-29, against the
synthetic NimbusDesk corpus. No mock-ups, no edited values.

| File | Shows |
| --- | --- |
| `answer-with-citations.jpg` | An answered question in extractive mode: the mode banner, extracted evidence with inline citation chips, and the retrieved passages with rank, RRF score, status badge and source line range. |
| `insufficient-evidence.jpg` | The abstention path. "What is NimbusDesk's phone support number?" is refused, with the coverage figure (0.50) against the calibrated threshold (0.55) and the missing terms named. |
| `retrieved-passages.jpg` | Retrieved-chunk inspection, including the per-method note that RRF scores measure rank agreement rather than relevance magnitude. |

The screenshots show the dark theme; the UI follows `prefers-color-scheme` and
has a light theme too.
