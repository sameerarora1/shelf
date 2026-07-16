# Instagram Post Extraction (OpenCLI browser bridge)

This branch adds an `InstagramPostExtractor` for `instagram.com/p/...` and
`instagram.com/reel/...` URLs. The existing YouTube, webpage, and X public
metadata paths are unchanged. When the Instagram tool, a logged-in session, or
the browser read is unavailable, Shelf falls back to the existing public
metadata extractor and records a structured failure reason.

## `agent-reach` was aspirational; `opencli` is what actually exists

The original design targeted a wrapper CLI literally named `agent-reach`
(`agent-reach doctor --json`, `pip install ".[agent-reach]"`). **That binary is
not installed on this machine and was never verified end-to-end.** The tool that
is actually installed is [`opencli`](https://www.npmjs.com/package/opencli)
(v1.8.6, "Make any website your CLI") — a general-purpose site-automation CLI
with a Chrome browser bridge. The extractor now drives `opencli` directly.

The legacy `agent-reach` module (`shelf/extractors/agent_reach.py`) is retained
only for its payload/text sanitization helpers; it is no longer on the live
path.

## Node.js requirement (read this first)

`opencli` requires **Node.js >= 20**. The default shell here has Node 18.20.5
active, which will fail. Before running Shelf's Instagram path you must either:

```bash
# Option A: put a modern Node on PATH (Node v22.23.1 is installed via nvm)
source ~/.nvm/nvm.sh && nvm use 22
python -m shelf.cli ingest data/instagram_posts.example.csv

# Option B: pin the absolute binary (its shebang still needs Node >= 20 on PATH)
export SHELF_OPENCLI_BIN=/Users/<you>/.nvm/versions/node/v22.23.1/bin/opencli
```

Confirm the tool and a logged-in session first (read-only):

```bash
opencli --version                 # -> 1.8.6
opencli instagram whoami -f json  # -> JSON identifying the logged-in account
```

`whoami` is used by Shelf **only as a boolean availability probe**. Its identity
fields (username / user_id / full_name of the logged-in account) are never
persisted to evidence or fixtures.

## Configuration (env vars)

| Env var | Default | Meaning |
| --- | --- | --- |
| `SHELF_OPENCLI_BIN` | `""` (resolve `opencli` on PATH) | Absolute path override for the binary |
| `SHELF_OPENCLI_INSTAGRAM_SESSION` | `shelf-ig` | Browser session name reused across posts |
| `SHELF_OPENCLI_BROWSER_WINDOW` | `background` | `--window` mode for `browser ... open` |
| `SHELF_OPENCLI_TIMEOUT_SECONDS` | `60` | Per-command subprocess timeout |

## What works vs. what does not

`opencli`'s documented Instagram surface (verified live, read-only):

- `opencli instagram profile <username> -f json` — clean structured public
  profile JSON (bio, followers, following, posts, verified, url). Reliable.
- `opencli instagram user <username> --limit N -f json` — recent posts as
  `{caption, comments, date, index, likes, type}`. **Note: no shortcode / id /
  URL field**, so it cannot resolve an arbitrary `/p/<shortcode>/` URL.
- There is **no native structured single-post API** for a given post URL.

To read a specific post URL, this branch uses the generic browser bridge and
scrapes the rendered Markdown:

```
opencli browser <session> open <url> --window background
opencli browser <session> extract     # JSON; page Markdown is in `.content`
opencli browser <session> close        # always run to release the tab lease
```

`parse_instagram_markdown()` (in `shelf/extractors/opencli.py`) best-effort
extracts:

- **author** — anchored on the canonical date link `[<date>](/<author>/reel|p/<shortcode>/)`; falls back to the first profile link.
- **canonical_url / media_type** — from that same canonical link (`/p/` feed posts often resolve to `/<author>/reel/<shortcode>/`).
- **display_date** (e.g. `April 5`, `October 23, 2025`) and **relative_time** (e.g. `14w`).
- **caption** — the text between the author's time marker and the first comment avatar (hashtag links are flattened to `#tag` text).
- **like / comment counts** — best-effort only (see fragility below).

### This is a scrape, and it is fragile

The parser reads a rendered DOM, not an API. Known limitations, all handled by
degrading rather than emitting wrong data:

- **Like/comment counts are only recovered for reels.** Reels render the totals
  as a suffixed, separator-less blob directly above the date link (e.g.
  `57.7K13.6K`); Shelf splits that only when both values carry a `K`/`M`/`B`
  suffix and are anchored to the date link. **Feed photo (`/p/`) posts** show
  likes as separate "N likes" text with no such blob, and some reels hide the
  count — in those cases Shelf returns `None` with a note rather than guessing.
  (An earlier global-search heuristic produced garbage like `0K`/`3B`; that was
  removed.)
- Carousels vs. reels vs. photos render differently; only fields the parser can
  confidently recover are emitted. A page with author/date but no isolable
  caption yields a **partial `metadata_only`** record (`error_code =
  opencli_instagram_partial`), never a fabricated caption.
- If the browser read or parse fails entirely, the extractor falls back to the
  public-metadata HTTP tier (unauthenticated `og:` tags), typically
  `metadata_only` or `blocked` for Instagram's login-walled pages.

## Extractor tiers

1. `opencli` doctor (binary resolvable + logged-in session) then browser
   open+extract+parse. Caption present -> `success`; partial fields -> traceable
   `metadata_only`.
2. Public-metadata fallback (`shelf/extractors/public_metadata.py`) when opencli
   is unavailable, the session is not logged in, or the read/parse fails.

## Smoke test

```bash
source ~/.nvm/nvm.sh && nvm use 22
SHELF_ANALYZER=deterministic python -m shelf.cli ingest data/instagram_posts.example.csv
python -m shelf.cli evaluate-analysis
```

## Evidence

Per-item files under `evidence/ingest-latest/raw/<item_id>/`:

- `instagram_opencli_response.json` — sanitized parsed fields, the commands run
  (binary basename only), and a boolean `logged_in` flag (never the logged-in
  identity).
- `instagram_opencli_markdown_limited.txt` — sanitized, length-capped Markdown.
- `instagram_opencli_error.json` — doctor / browser / parse failures.
- `public_metadata_response.json` / `public_metadata_error.json` — fallback tier.

A committed, sanitized live run for this branch lives in
`evidence/instagram-live/` (5 real URLs from `data/instagram_posts.example.csv`
plus one forced-unavailable fallback demo).

### Actual live result (not hypothetical)

All 5 example URLs returned `success` with a real caption, author, canonical
URL, and date. Like/comment counts were recovered only for the two reels:

| item | author | type | caption | likes / comments |
| --- | --- | --- | --- | --- |
| ig_post_1 | brycenwood.ai | reel | yes | 57.7K / 13.6K |
| ig_post_2 | socialtypro | p (photo) | yes | none (not shown for photos) |
| ig_post_3 | vardy.mov | reel | yes | 10.2K / 4.6K |
| ig_post_4 | thelegacyinvestingshow | reel | yes | none (hidden/unsuffixed) |
| ig_post_5 | theedgarr | p (photo) | yes | none (not shown for photos) |

`ig_fallback_demo` shows the opencli-unavailable path degrading to the public
metadata tier (`blocked`).

## Privacy

Do not commit `.env`, cookies, tokens, browser profiles, Chrome user data, or
`whoami` output. Instagram access uses your local logged-in Chrome session via
opencli; only posts visible to that session are readable. Public target-post and
profile data (the account being *looked at*) is fine to persist; the logged-in
account's own identity is not.
