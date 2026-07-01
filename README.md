# Shelf

Shelf is an Intelligent Saved Content System. It routes saved URLs, extracts public text or metadata when available, preserves visible failures, analyzes and organizes records, and supports simple search/evaluation.

## Setup for Reproduction

```bash
cd shelf
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

Or:

```bash
make setup
```

## OpenRouter Analyzer

The checked-in `.env.example` is configured for the LLM analyzer with NVIDIA
Nemotron through OpenRouter. Install the optional OpenAI SDK extra and configure
local environment variables:

```bash
source .venv/bin/activate
pip install -e ".[dev,openai]"
cp .env.example .env
```

```env
SHELF_ANALYZER=openrouter
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_TIMEOUT_SECONDS=30
```

`OPENROUTER_API_KEY` must be set in `.env` or the shell when
`SHELF_ANALYZER=openrouter`.

The deterministic analyzer remains available by setting
`SHELF_ANALYZER=deterministic`.

The OpenRouter analyzer receives the saved item's raw data:
- title
- description
- extracted page text or transcript
- source metadata, URL
- current category list

The LLM-based analyzer must either reuse a semantically matching existing category, create a concise new category, or return `Needs Review` when the content is too limited. Newly created categories are retained by the organizer during the ingest run, so later items can reuse them.

## CLI Commands

Deterministic analyzer, no API key required:

```bash
source .venv/bin/activate
python -m shelf.cli init
SHELF_ANALYZER=deterministic python -m shelf.cli ingest data/urls.csv
python -m shelf.cli organize
python -m shelf.cli search "high protein vegetarian dinner" --top-k 3
python -m shelf.cli evaluate data/retrieval_queries.csv
python -m shelf.cli evaluate-analysis
```

LLM-based analyzer with NVIDIA Nemotron through OpenRouter:

You can either put the OpenRouter variables in `.env` and run
`python -m shelf.cli ingest data/urls.csv` normally after activating the venv.

OR

You may verbosely embed your `.env` specifications via CLI:

```bash
source .venv/bin/activate
pip install -e ".[openai]"
python -m shelf.cli init
export OPENROUTER_API_KEY="sk-or-v1-..."
SHELF_ANALYZER=openrouter \
OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1 \
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free \
OPENROUTER_TIMEOUT_SECONDS=30 \
python -m shelf.cli ingest data/urls.csv
python -m shelf.cli organize
python -m shelf.cli search "high protein vegetarian dinner" --top-k 3
python -m shelf.cli evaluate data/retrieval_queries.csv
python -m shelf.cli evaluate-analysis
```


## Demo Run from Checkpoint 1 (for Reproduction)

```bash
python -m shelf.cli init
python -m shelf.cli ingest data/urls.csv
python -m shelf.cli organize
python -m shelf.cli search "vegetarian dinner" --top-k 3
python -m shelf.cli evaluate data/retrieval_queries.csv
python -m shelf.cli evaluate-analysis
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

## Analyzer-Based Demo Run from Checkpoint 2 (for Reproduction)

This example uses the LLM-backed analyzer path. Put the OpenRouter variables in
`.env`, or export them in the shell before ingest.

```bash
source .venv/bin/activate
pip install -e ".[dev,openai]"
python -m shelf.cli init
python -m shelf.cli ingest data/urls.csv
python -m shelf.cli organize
python -m shelf.cli search "high protein vegetarian dinner" --top-k 3
python -m shelf.cli evaluate data/retrieval_queries.csv
python -m shelf.cli evaluate-analysis
```

Example output from one analyzer-backed run:

```text
Initialized Shelf project at /Users/sameerarora/Desktop/GT2026Su/CS4365/cs4365-shelf/shelf
SQLite path: /Users/sameerarora/Desktop/GT2026Su/CS4365/cs4365-shelf/shelf/.shelf/shelf.sqlite3
Ingested 10 items
Raw evidence: /Users/sameerarora/Desktop/GT2026Su/CS4365/cs4365-shelf/shelf/evidence/ingest-latest/raw
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
    "item_id": "veg_yt_1",
    "score": 0.6538867731884939,
    "summary": "Video showcasing six high-protein vegetarian dinner recipes from Tasty.",
    "title": "6 High-Protein Vegetarian Dinners"
  },
  {
    "collection": "Vegetarian Recipes",
    "extraction_status": "success",
    "item_id": "veg_yt_2",
    "score": 0.1877088453192677,
    "summary": "The video presents three high-protein vegan meals each with over 30g protein, made in 20 minutes: Smashed Edamame Toast, Tofu Noodle Bowl with Almond Butter Sauce, and Garlicky Quinoa and Lentils with Tofu Ricotta.",
    "title": "High-Protein Vegan Meals EVERYONE Should Know"
  },
  {
    "collection": "Vegetarian Recipes",
    "extraction_status": "success",
    "item_id": "veg_web_2",
    "score": 0.14584214439016668,
    "summary": "Budget Bytes vegetarian recipe archive featuring over 400 budget-friendly meat-free recipes for all meals, with cost-per-serving breakdowns and many vegan options.",
    "title": "Vegetarian Recipes Archives"
  }
]
```

```json
{
  "metrics": {
    "evaluated_query_count": 9,
    "mrr": 1.0,
    "precision_at_3": 0.6666666666666666,
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
      "returned_item_ids": ["invest_web_2", "invest_yt_1", "social_x_1"]
    },
    {
      "precision_at_3": 0.6666666666666666,
      "query": "beginner bodyweight workout",
      "query_id": "q3",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["gym_web_1", "gym_yt_1"],
      "returned_item_ids": ["gym_web_1", "gym_yt_1", "invest_yt_1"]
    },
    {
      "precision_at_3": 0.3333333333333333,
      "query": "vegetable chickpea sheet pan dinner",
      "query_id": "q4",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["veg_web_1"],
      "returned_item_ids": ["veg_web_1", "veg_web_2", "veg_yt_1"]
    },
    {
      "precision_at_3": 0.3333333333333333,
      "query": "budget vegetarian recipe archive",
      "query_id": "q5",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["veg_web_2"],
      "returned_item_ids": ["veg_web_2", "veg_yt_1", "veg_web_1"]
    },
    {
      "precision_at_3": 1.0,
      "query": "high protein vegan meals tofu",
      "query_id": "q6",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["veg_web_1", "veg_yt_1", "veg_yt_2"],
      "returned_item_ids": ["veg_yt_1", "veg_yt_2", "veg_web_1"]
    },
    {
      "precision_at_3": 1.0,
      "query": "investment education metadata limited needs review",
      "query_id": "q7",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["invest_web_1", "invest_web_2", "social_x_1"],
      "returned_item_ids": ["invest_web_1", "social_x_1", "invest_web_2"]
    },
    {
      "precision_at_3": 0.6666666666666666,
      "query": "free tools for investing x market",
      "query_id": "q8",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["invest_web_1", "invest_web_2", "social_x_1"],
      "returned_item_ids": ["social_x_1", "invest_web_2", "invest_yt_1"]
    },
    {
      "precision_at_3": 0.3333333333333333,
      "query": "calisthenics bodyweight exercise reference",
      "query_id": "q9",
      "reciprocal_rank": 1.0,
      "relevant_item_ids": ["gym_web_1", "gym_yt_1"],
      "returned_item_ids": ["gym_web_1", "invest_web_1", "invest_web_2"]
    }
  ]
}
```

```json
{
  "metrics": {
    "analysis_modes": {
      "deterministic": 1,
      "openrouter": 9
    },
    "fallback_behavior_valid_count": 7,
    "fallback_behavior_valid_rate": 0.7,
    "item_count": 10,
    "metadata_complete_count": 10,
    "metadata_complete_rate": 1.0,
    "overall_pass_count": 1,
    "overall_pass_rate": 0.1,
    "status": "evaluated",
    "structured_output_valid_count": 8,
    "structured_output_valid_rate": 0.8,
    "tag_agreement_count": 1,
    "tag_agreement_rate": 0.1,
    "trace_coverage_count": 10,
    "trace_coverage_rate": 1.0
  },
  "results": [
    {
      "actual_collection": "Gym and Exercise",
      "analysis_mode": "openrouter",
      "expected_collection": "Gym and Exercise",
      "expected_topic": "exercise",
      "extraction_status": "success",
      "failure_reasons": ["expected topic missing: exercise"],
      "fallback_behavior_valid": true,
      "item_id": "gym_web_1",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "public_webpage",
      "structured_output_valid": true,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Gym and Exercise",
      "analysis_mode": "openrouter",
      "expected_collection": "Gym and Exercise",
      "expected_topic": "exercise",
      "extraction_status": "success",
      "failure_reasons": ["expected topic missing: exercise"],
      "fallback_behavior_valid": true,
      "item_id": "gym_yt_1",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "youtube",
      "structured_output_valid": true,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Needs Review",
      "analysis_mode": "openrouter",
      "expected_collection": "Investment Education",
      "expected_topic": "investment",
      "extraction_status": "blocked",
      "failure_reasons": [
        "summary is missing",
        "expected topic missing: investment",
        "fallback item lacks needs-review intent tag"
      ],
      "fallback_behavior_valid": false,
      "item_id": "invest_web_1",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "public_webpage",
      "structured_output_valid": false,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Needs Review",
      "analysis_mode": "openrouter",
      "expected_collection": "Investment Education",
      "expected_topic": "investment",
      "extraction_status": "blocked",
      "failure_reasons": [
        "summary is missing",
        "expected topic missing: investment",
        "fallback item lacks needs-review intent tag"
      ],
      "fallback_behavior_valid": false,
      "item_id": "invest_web_2",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "public_webpage",
      "structured_output_valid": false,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Investment Education",
      "analysis_mode": "openrouter",
      "expected_collection": "Investment Education",
      "expected_topic": "investment",
      "extraction_status": "success",
      "failure_reasons": ["expected topic missing: investment"],
      "fallback_behavior_valid": true,
      "item_id": "invest_yt_1",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "youtube",
      "structured_output_valid": true,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Metadata Only",
      "analysis_mode": "openrouter",
      "expected_collection": "Investment Education",
      "expected_topic": "investment",
      "extraction_status": "metadata_only",
      "failure_reasons": [
        "expected topic missing: investment",
        "metadata-only item lacks metadata-only intent tag"
      ],
      "fallback_behavior_valid": false,
      "item_id": "social_x_1",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "x_public",
      "structured_output_valid": true,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Vegetarian Recipes",
      "analysis_mode": "deterministic",
      "expected_collection": "Vegetarian Recipes",
      "expected_topic": "vegetarian",
      "extraction_status": "success",
      "failure_reasons": [],
      "fallback_behavior_valid": true,
      "item_id": "veg_web_1",
      "metadata_complete": true,
      "overall_pass": true,
      "source_type": "public_webpage",
      "structured_output_valid": true,
      "tag_agreement": true,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Vegetarian Recipes",
      "analysis_mode": "openrouter",
      "expected_collection": "Vegetarian Recipes",
      "expected_topic": "vegetarian",
      "extraction_status": "success",
      "failure_reasons": ["expected topic missing: vegetarian"],
      "fallback_behavior_valid": true,
      "item_id": "veg_web_2",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "public_webpage",
      "structured_output_valid": true,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Vegetarian Recipes",
      "analysis_mode": "openrouter",
      "expected_collection": "Vegetarian Recipes",
      "expected_topic": "vegetarian",
      "extraction_status": "success",
      "failure_reasons": ["expected topic missing: vegetarian"],
      "fallback_behavior_valid": true,
      "item_id": "veg_yt_1",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "youtube",
      "structured_output_valid": true,
      "tag_agreement": false,
      "trace_coverage_valid": true
    },
    {
      "actual_collection": "Vegetarian Recipes",
      "analysis_mode": "openrouter",
      "expected_collection": "Vegetarian Recipes",
      "expected_topic": "vegetarian",
      "extraction_status": "success",
      "failure_reasons": ["expected topic missing: vegetarian"],
      "fallback_behavior_valid": true,
      "item_id": "veg_yt_2",
      "metadata_complete": true,
      "overall_pass": false,
      "source_type": "youtube",
      "structured_output_valid": true,
      "tag_agreement": false,
      "trace_coverage_valid": true
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

## Analyzer Acceptance Evaluation - Checkpoint 2

`python -m shelf.cli evaluate-analysis` evaluates persisted analyzer output against checkpoint 2 acceptance criteria:

- structured output validity for summary, topics, content type, intent tags, and analysis mode;
- metadata completeness for successful extraction, metadata-only fallback, and blocked/failed records;
- tag agreement between theme hints, expected topics, and successful collection assignments;
- fallback behavior for metadata-only and needs-review records;
- trace coverage across routing, extraction, validation, analysis, organization, indexing, and persistence stages.

The same evaluator can compare deterministic and OpenRouter-backed analyzer runs because it reads normalized `SavedItem` records and trace events from SQLite.

## Supported Sources

- YouTube public URLs use `shelf.extractors.youtube.YouTubeExtractor`, which calls
  `yt-dlp` for metadata and English subtitles/transcripts when available. Shelf
  does not download video or audio.
- Public webpages use `shelf.extractors.webpage.WebPageExtractor`, with bounded
  `httpx` requests and `trafilatura` text extraction.
- Blocked or limited public social links use
  `shelf.extractors.public_metadata.PublicMetadataExtractor` to preserve public
  metadata when available, or a normalized blocked/metadata-only fallback record
  when full text cannot be retrieved.
- Unsupported or unsafe URLs are rejected with visible normalized records and
  trace entries rather than being silently dropped.

Experimental social extraction work is intentionally kept on separate branches
from `main` for closed, isolated testing before any merge:

- `support-x-posts` adds an experimental `shelf.extractors.x.XPostExtractor`
  for `x.com` and `twitter.com` status URLs.
- `support-ig-posts` adds an experimental
  `shelf.extractors.instagram.InstagramPostExtractor` for Instagram `/p/...`
  post URLs.

Both branches explore Agent-Reach as an optional backend, following its
[English README design philosophy](https://github.com/Panniantong/Agent-Reach/blob/main/docs/README_en.md#design-philosophy).
Agent-Reach is wrapped behind Shelf's existing extractor and normalization flow:
it can provide candidate post data, but it does not replace the deterministic
routing, fallback, evidence, trace, and normalized `SavedItem` pipeline.

## Specifications

- X/Twitter and Instagram post extraction are experimental branch work, not
  guaranteed baseline `main` support unless those branches are merged.
- Social and webpage retrieval can be unavailable, blocked, rate-limited, or
  dependent on browser/session state. In those cases Shelf may only produce
  metadata-only or blocked/failure records.
- Do not commit secrets, cookies, session files, `.env`, Agent-Reach state,
  browser profiles, or command output containing private session data.
- The current retrieval baseline is `shelf.retrieval.index.TfidfSearchIndex`.
  TF-IDF is lightweight and reproducible, but it is limited compared with
  semantic or vector retrieval.
- LLM-backed analysis currently uses OpenRouter. The checked-in configuration
  defaults to `OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free` with
  `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`.
- LLM-backed analysis should fail over cleanly when API keys, provider access,
  or model responses are unavailable. The OpenRouter analyzer uses the
  deterministic analyzer as its fallback path.
