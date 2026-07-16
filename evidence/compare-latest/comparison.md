# Checkpoint 3 - Analyzer Comparison Across Backends

- Generated: `2026-07-15T23:46:52.411841+00:00`
- Dataset: `data/urls.csv`
- Retrieval labels: `data/retrieval_queries.csv`
- Items: 10 | Traces: 83
- Analyzer config: model `nvidia/nemotron-3-ultra-550b-a55b:free`, api_key_configured=True
- Best backend: **deterministic** (accept pass 1.0, P@3 0.7407407407407407)

| Model / Backend | Mode | Accept Pass | Struct OK | Tag Agree | Fallback OK | P@3 | MRR | Fallbacks | Mean ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deterministic | deterministic | 1.000 | 1.000 | 1.000 | 1.000 | 0.741 | 1.000 | 0 | 0.601 |
| nvidia/nemotron-3-ultra-550b-a55b:free | openrouter | 0.100 | 0.800 | 0.100 | 0.700 | 0.667 | 1.000 | 0 | 8079.639 |
| unavailable | openrouter | 1.000 | 1.000 | 1.000 | 1.000 | 0.741 | 1.000 | 10 | 0.816 |

## Failure reasons and fallback notes

- `nvidia/nemotron-3-ultra-550b-a55b:free` (openrouter)
  - acceptance gap: expected topic missing: exercise
  - acceptance gap: expected topic missing: investment
  - acceptance gap: expected topic missing: vegetarian
  - acceptance gap: fallback item lacks needs-review intent tag
  - acceptance gap: metadata-only item lacks metadata-only intent tag
  - acceptance gap: summary is missing
- `unavailable` (openrouter)
  - fallback: OpenRouter analyzer failed; deterministic fallback used: OpenRouterRequestError
