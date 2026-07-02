# Agent-Reach X Post Extraction

This branch adds an optional `XPostExtractor` for `x.com` and `twitter.com`
status URLs. The existing YouTube and public-webpage extractors are unchanged.
If Agent-Reach or the active X backend is unavailable, Shelf falls back to the
existing public metadata path and records the Agent-Reach failure on the item.

## Setup

Install Shelf with the optional Agent-Reach extra:

```bash
pip install -e ".[dev,agent-reach]"
agent-reach install --env=auto --channels=twitter
agent-reach doctor --json
```

Agent-Reach currently routes X through `twitter-cli`, with OpenCLI/bird as
fallback candidates. Direct post extraction in this branch only uses the
documented `twitter tweet URL_OR_ID` path. By default Shelf runs:

```bash
twitter tweet "{url}" --json
```

Override it when testing another backend:

```bash
export SHELF_AGENT_REACH_X_COMMAND='twitter tweet {url} --json'
export SHELF_AGENT_REACH_TIMEOUT_SECONDS=30
```

## Credentials And Sessions

`twitter-cli` requires authorized X access. Follow Agent-Reach's guidance to
configure cookies or a browser-backed session. Do not commit `.env`,
`~/.agent-reach/`, cookies, tokens, browser profiles, or command output that
contains private session data.

## Smoke Test

```bash
SHELF_ANALYZER=deterministic python -m shelf.cli ingest data/x_posts.example.csv
python -m shelf.cli evaluate-analysis
```

Live extraction may return metadata-only or blocked records if X rejects the
session, credentials are missing, rate limits apply, or the post is not visible
to the configured account.

## Evidence

Per-item files are written under `evidence/ingest-latest/raw/<item_id>/`:

- `x_agent_reach_response.json` for sanitized successful structured output.
- `x_agent_reach_stdout_limited.txt` for sanitized command stdout.
- `x_agent_reach_error.json` for doctor/backend failures.
- `public_metadata_response.json` or `public_metadata_error.json` when fallback
  metadata extraction runs.

