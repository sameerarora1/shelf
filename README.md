# Shelf

Shelf is an Intelligent Saved Content System. It routes saved URLs, extracts public text or metadata when available, preserves visible failures, analyzes and organizes records, and supports simple search/evaluation.

## Setup

```bash
cd shelf
python3.11 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"
```

Or:

```bash
make setup
```

## CLI Commands

```bash
python -m shelf.cli init
python -m shelf.cli ingest data/urls.csv
python -m shelf.cli organize
python -m shelf.cli search "high protein vegetarian dinner" --top-k 3
python -m shelf.cli evaluate data/retrieval_queries.csv
```

## Demo Run

```bash
python -m shelf.cli init
python -m shelf.cli ingest data/urls.csv
python -m shelf.cli organize
python -m shelf.cli search "vegetarian dinner" --top-k 3
python -m shelf.cli evaluate data/retrieval_queries.csv
```

Example output from one run:

```text
Initialized Shelf project at /Users/sameerarora/Desktop/GT2026Su/CS4365/ckpt-1/shelf
SQLite path: /Users/sameerarora/Desktop/GT2026Su/CS4365/ckpt-1/shelf/.shelf/shelf.sqlite3
Ingested 10 items
Raw evidence: /Users/sameerarora/Desktop/GT2026Su/CS4365/ckpt-1/shelf/evidence/ingest-latest/raw
```

```json
{
  "Gym and Exercise": ["gym_web_1", "gym_yt_1"],
  "Investment Education": ["invest_yt_1"],
  "Metadata Only": ["social_x_1"],
  "Needs Review": ["invest_web_1", "invest_web_2"],
  "Vegetarian Recipes": ["veg_web_1", "veg_web_2", "veg_yt_1", "veg_yt_2"]
}
```

```json
[
  {
    "collection": "Vegetarian Recipes",
    "extraction_status": "success",
    "item_id": "veg_web_2",
    "score": 0.21105925432483538,
    "summary": "Vegetarian Recipes Discover budget-friendly vegetarian recipes that are loved by vegetarians and omnivores alike! No mystery ingredients here, just simple vegetarian food made easy and delicious, without the meat.",
    "title": "Vegetarian Recipes Archives"
  },
  {
    "collection": "Vegetarian Recipes",
    "extraction_status": "success",
    "item_id": "veg_yt_1",
    "score": 0.1475660088587286,
    "summary": "[Music] so [Music] foreign [Music] you",
    "title": "6 High-Protein Vegetarian Dinners"
  },
  {
    "collection": "Vegetarian Recipes",
    "extraction_status": "success",
    "item_id": "veg_web_1",
    "score": 0.13119086270677618,
    "summary": "This vegetable and chickpea sheet pan dinner with broccoli, sweet potato and zucchini is the perfect vegan weeknight dish! Make it with minimal effort and simple ingredients, and serve with a side of your choice like rice or quinoa.",
    "title": "Vegan Sheet Pan Dinner"
  }
]
```

```json
{
  "metrics": {
    "evaluated_query_count": 3,
    "mrr": 1.0,
    "precision_at_3": 0.7777777777777778,
    "status": "evaluated",
    "top_k": 3
  },
  "results": [
    {
      "precision_at_3": 1.0,
      "query": "high protein vegetarian dinner",
      "query_id": "q1",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["veg_web_1", "veg_web_2", "veg_yt_1", "veg_yt_2"],
      "returned_item_ids": ["veg_yt_1", "veg_yt_2", "veg_web_2"]
    },
    {
      "precision_at_3": 0.6666666666666666,
      "query": "index funds beginner investing",
      "query_id": "q2",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["invest_web_1", "invest_web_2", "invest_yt_1"],
      "returned_item_ids": ["invest_yt_1", "social_x_1", "invest_web_1"]
    },
    {
      "precision_at_3": 0.6666666666666666,
      "query": "beginner bodyweight workout",
      "query_id": "q3",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["gym_web_1", "gym_yt_1"],
      "returned_item_ids": ["gym_web_1", "gym_yt_1"]
    }
  ]
}
```

## Make Targets

```bash
make setup
make test
```

## Evidence

The ingest command writes local evidence files:

```text
evidence/
  output.json
  items.jsonl
  traces.jsonl
```

`output.json` contains normalized items and collection assignments. `traces.jsonl` contains the decision trace for each URL.

## Supported Sources

- YouTube public URLs: metadata through `yt-dlp`, optional English subtitles when available, never video/audio download.
- Public webpages: bounded `httpx` request plus `trafilatura` extraction.
- Instagram/X public links: public metadata attempt only, then metadata-only or blocked fallback.
- Unsupported/unsafe URLs: rejected with visible normalized records and traces.

## Limitations

- The deterministic analyzer is intentionally simple and reproducible.
- Live extraction depends on public network access and source availability.
- TF-IDF retrieval is a baseline, not semantic search.

## Reproduction Steps

```bash
cd shelf
make setup
make test
python -m shelf.cli ingest data/urls.csv
```

Then inspect `evidence/output.json` and `evidence/traces.jsonl`.
