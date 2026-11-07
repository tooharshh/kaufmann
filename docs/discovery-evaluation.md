# Product discovery evaluation

The November 7, 2026 experiment rejected hybrid retrieval. Production retains PostgreSQL full-text search with Cerebras intent normalization and deterministic metadata filters. No pgvector migration or embedding runtime was added.

The evaluation used all 20,000 catalog rows, a free local quantized multilingual E5-small model, and disposable PostgreSQL 17/pgvector 0.8.1. Forty queries covered English, Telugu, romanized English-Telugu mixing, and no-answer cases. Ranking used source-audited rules rather than independent human judgments. Latencies are warm local candidate retrieval, excluding Cerebras planning, network/API overhead and speech.

| Method | Precision@5 | nDCG@5 | p50 / p95 |
| --- | ---: | ---: | ---: |
| Cerebras keyword plan + indexed FTS | 0.897 | 0.926 | 1.33 / 6.26 ms |
| Raw-query vector search | 0.564 | 0.579 | 25.08 / 152.03 ms |
| Planner FTS + vectors, equal RRF | 0.800 | 0.830 | 27.03 / 158.29 ms |

Telugu nDCG fell from 0.950 to 0.780; mixed-language nDCG fell from 0.892 to 0.796. Hybrid returned irrelevant products on five of seven no-answer queries; lexical search returned none. All methods preserved hard price/stock/attribute restrictions, and eighteen additional validation probes passed. Gift relevance labels were narrow; excluding that intent still favored FTS (0.946 versus 0.858).

A separate same-machine index comparison reduced lexical p95 from 91.67 to 6.73 ms. Production had only a primary-key product index at evaluation time. A matching GIN index is the recommended next database change, subject to separate migration review; it has not been applied.

The precise aggregate measurements, corpus/model hashes and promotion-gate results are retained in [the evidence record](evidence/discovery-results.json). Temporary evaluation code, model downloads and generated snapshots were archived outside the application repository during release cleanup. No paid embedding service or external vector database was used.

This is a small fixture-based result for one model/fusion configuration, not evidence that all hybrid approaches are unsuitable. Reconsider only with independently judged held-out queries, stronger multilingual relevance and calibrated no-answer behavior.
