# Agent-Reach Instagram Post Extraction

This branch adds an optional `InstagramPostExtractor` for
`instagram.com/p/...` URLs. The existing YouTube, webpage, and X public metadata
paths are unchanged. If Agent-Reach, OpenCLI, a browser session, or a configured
direct post command is unavailable, Shelf falls back to the existing public
metadata extractor and records a structured failure reason.

## Setup

Install Shelf with the optional Agent-Reach extra:

```bash
pip install -e ".[dev,agent-reach]"
agent-reach install --env=auto --channels=instagram
agent-reach doctor --json
```

Agent-Reach's English docs currently describe Instagram via OpenCLI on a desktop
Chrome session, with commands for user search, profile, recent user posts,
Explore, and saved items. They do not document a stable direct `/p/...` post
read command. This branch therefore requires an explicit command template before
attempting live post extraction:

```bash
export SHELF_AGENT_REACH_INSTAGRAM_COMMAND='opencli instagram post {url} -f json'
export SHELF_AGENT_REACH_TIMEOUT_SECONDS=30
```

Use the command only after verifying it against your installed OpenCLI version.
Without this environment variable, the extractor intentionally records a
metadata-only or blocked fallback instead of pretending direct post extraction
worked.

## Credentials And Sessions

Instagram access requires a local desktop browser session through OpenCLI:

- Chrome must have the OpenCLI extension installed.
- The user must be logged into `instagram.com` in that browser.
- Only posts visible to that authorized session should be extracted.

Do not commit `.env`, `~/.agent-reach/`, cookies, tokens, browser profiles,
Chrome user data, or command output that contains private session data.

## Smoke Test

```bash
SHELF_ANALYZER=deterministic python -m shelf.cli ingest data/instagram_posts.example.csv
python -m shelf.cli evaluate-analysis
```

Live extraction may return metadata-only or blocked records if the command
template is not configured, OpenCLI cannot reach the browser, Instagram requires
login or verification, rate limits apply, or the post is not visible to the
configured account.

## Evidence

Per-item files are written under `evidence/ingest-latest/raw/<item_id>/`:

- `instagram_agent_reach_response.json` for sanitized successful structured
  output.
- `instagram_agent_reach_stdout_limited.txt` for sanitized command stdout.
- `instagram_agent_reach_error.json` for doctor/backend/command failures.
- `public_metadata_response.json` or `public_metadata_error.json` when fallback
  metadata extraction runs.

