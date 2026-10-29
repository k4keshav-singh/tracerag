# Screenshots

Captured from a real run of TraceRAG in a browser on 2026-10-29, against the
synthetic NimbusDesk corpus. No mock-ups, no edited values.

| File | Shows |
| --- | --- |
| `hero-light.jpg` | Hero and query console in the light theme: the drifting gradient mesh, animated stat cards, and the label-over-value control row beside the violet call to action. |
| `hero-dark.jpg` | The same view in the dark theme, toggled from the header. |
| `answer-with-citations.jpg` | An answered question in extractive mode: the mode banner, extracted evidence with inline citation chips, and the coverage meter. |
| `insufficient-evidence.jpg` | The abstention path. "What is NimbusDesk's phone support number?" is refused, with the coverage meter in amber against the 0.55 threshold mark, and the question's terms shown green where found and red where not. |
| `retrieved-passages.jpg` | Retrieved-chunk inspection and the document sidebar, including the per-method note that RRF scores measure rank agreement rather than relevance magnitude. |

Both themes ship. The interface follows `prefers-color-scheme` on first visit
and remembers an explicit choice in `localStorage` afterwards.
