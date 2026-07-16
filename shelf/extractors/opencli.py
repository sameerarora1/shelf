"""OpenCLI-backed Instagram post reader.

The ``support-ig-posts`` branch was originally written against a wrapper CLI
literally named ``agent-reach`` (see :mod:`shelf.extractors.agent_reach`). That
binary is not installed. The tool that actually exists on this machine is
``opencli`` ("Make any website your CLI"), a general-purpose site-automation CLI
with a Chrome browser bridge.

``opencli`` exposes no native structured single-post API for an arbitrary
``/p/<shortcode>/`` URL. What it does expose is a generic browser bridge:

    opencli browser <session> open <url> --window background
    opencli browser <session> extract
    opencli browser <session> close

``extract`` returns JSON whose ``content`` field is a Markdown rendering of the
loaded page. This module drives those commands and best-effort parses that
Markdown into structured fields. The parse is fragile by nature (it scrapes a
rendered DOM, not an API), so callers must treat missing fields as an honest
partial result and degrade to metadata-only rather than emit wrong data.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from shelf.extractors.agent_reach import sanitize_agent_reach_text
from shelf.extractors.base import sanitize_error

# Instagram usernames: letters, digits, periods, underscores.
_USERNAME = r"[A-Za-z0-9._]+"


@dataclass(frozen=True)
class OpenCliDoctorResult:
    """Availability probe for opencli's Instagram surface.

    ``session_active`` is derived from ``instagram whoami`` but never carries the
    logged-in account's identity fields (username / user_id / full_name) so that
    private session data is never persisted to evidence.
    """

    available: bool
    binary: str | None = None
    session_active: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class OpenCliPostRead:
    """Raw result of a browser open+extract+close cycle."""

    ok: bool
    url: str
    markdown: str = ""
    argv_log: list[str] = field(default_factory=list)
    returncode: int | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ParsedInstagramPost:
    """Best-effort structured fields scraped from the rendered Markdown."""

    author: str | None = None
    caption: str | None = None
    like_count_display: str | None = None
    comment_count_display: str | None = None
    display_date: str | None = None
    relative_time: str | None = None
    media_type: str | None = None
    canonical_url: str | None = None
    fields_found: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def has_caption(self) -> bool:
        return bool(self.caption)

    @property
    def has_any_field(self) -> bool:
        return bool(self.fields_found)


class OpenCliInstagramRunner:
    """Drives the installed ``opencli`` binary via its Chrome browser bridge."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        binary: str = "",
        session_name: str = "shelf-ig",
        window_mode: str = "background",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.configured_binary = binary
        self.session_name = session_name
        self.window_mode = window_mode

    def _resolve_binary(self) -> str | None:
        # ``shutil.which`` resolves both a bare name on PATH and an absolute path
        # (returning it only when it is an executable file), so a misconfigured
        # SHELF_OPENCLI_BIN cleanly reports "not installed".
        return shutil.which(self.configured_binary or "opencli")

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[str] | None:
        return subprocess.run(
            argv,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
        )

    def doctor(self) -> OpenCliDoctorResult:
        binary = self._resolve_binary()
        if binary is None:
            return OpenCliDoctorResult(
                available=False,
                error_code="opencli_not_installed",
                error_message=(
                    "opencli CLI is not resolvable. Install it (npm i -g opencli), ensure "
                    "Node.js >= 20 is active (e.g. `nvm use 22`), or set SHELF_OPENCLI_BIN "
                    "to the absolute binary path."
                ),
            )
        try:
            completed = self._run([binary, "instagram", "whoami", "-f", "json"])
        except subprocess.TimeoutExpired as exc:
            return OpenCliDoctorResult(
                available=False,
                binary=binary,
                error_code="opencli_whoami_timeout",
                error_message=sanitize_error(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return OpenCliDoctorResult(
                available=False,
                binary=binary,
                error_code="opencli_whoami_failed",
                error_message=sanitize_error(exc),
            )
        if completed is None or completed.returncode != 0:
            stderr = completed.stderr if completed else ""
            stdout = completed.stdout if completed else ""
            return OpenCliDoctorResult(
                available=False,
                binary=binary,
                error_code="opencli_instagram_session_unavailable",
                error_message=sanitize_agent_reach_text(stderr or stdout)
                or "opencli reported no logged-in Instagram session.",
            )
        # Parse only for a boolean liveness signal. Deliberately drop every
        # identity field (username / user_id / full_name) so private session
        # data never reaches disk.
        session_active = _whoami_indicates_session(completed.stdout)
        if not session_active:
            return OpenCliDoctorResult(
                available=False,
                binary=binary,
                session_active=False,
                error_code="opencli_instagram_session_unavailable",
                error_message="opencli whoami did not confirm a logged-in Instagram session.",
            )
        return OpenCliDoctorResult(available=True, binary=binary, session_active=True)

    def read_post(self, url: str) -> OpenCliPostRead:
        binary = self._resolve_binary()
        if binary is None:
            return OpenCliPostRead(
                ok=False,
                url=url,
                error_code="opencli_not_installed",
                error_message="opencli CLI is not resolvable.",
            )
        session = self.session_name
        argv_log: list[str] = []
        open_argv = [
            binary,
            "browser",
            session,
            "open",
            url,
            "--window",
            self.window_mode,
        ]
        extract_argv = [binary, "browser", session, "extract"]
        close_argv = [binary, "browser", session, "close"]
        try:
            opened = self._run(open_argv)
            argv_log.append(_sanitize_argv(open_argv))
            if opened is None or opened.returncode != 0:
                return OpenCliPostRead(
                    ok=False,
                    url=url,
                    argv_log=argv_log,
                    returncode=opened.returncode if opened else None,
                    error_code="opencli_browser_open_failed",
                    error_message=sanitize_agent_reach_text(
                        (opened.stderr or opened.stdout) if opened else ""
                    ),
                )
            extracted = self._run(extract_argv)
            argv_log.append(_sanitize_argv(extract_argv))
            if extracted is None or extracted.returncode != 0:
                return OpenCliPostRead(
                    ok=False,
                    url=url,
                    argv_log=argv_log,
                    returncode=extracted.returncode if extracted else None,
                    error_code="opencli_browser_extract_failed",
                    error_message=sanitize_agent_reach_text(
                        (extracted.stderr or extracted.stdout) if extracted else ""
                    ),
                )
            markdown = _extract_content(extracted.stdout)
            if not markdown:
                return OpenCliPostRead(
                    ok=False,
                    url=url,
                    argv_log=argv_log,
                    returncode=extracted.returncode,
                    error_code="opencli_extract_empty",
                    error_message="opencli extract returned no page content.",
                )
            return OpenCliPostRead(
                ok=True,
                url=url,
                markdown=markdown,
                argv_log=argv_log,
                returncode=0,
            )
        except subprocess.TimeoutExpired as exc:
            return OpenCliPostRead(
                ok=False,
                url=url,
                argv_log=argv_log,
                error_code="opencli_browser_timeout",
                error_message=sanitize_error(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return OpenCliPostRead(
                ok=False,
                url=url,
                argv_log=argv_log,
                error_code="opencli_browser_failed",
                error_message=sanitize_error(exc),
            )
        finally:
            # Always release the tab lease, even on failure. Ignore its result.
            try:
                self._run(close_argv)
            except Exception:  # noqa: BLE001
                pass


def _whoami_indicates_session(stdout: str) -> bool:
    text = (stdout or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Non-JSON but non-empty success output still implies a session.
        return True
    if isinstance(payload, dict):
        return any(payload.get(key) for key in ("user_id", "username", "pk", "id"))
    return bool(payload)


def _extract_content(stdout: str) -> str:
    text = (stdout or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Some opencli versions may print raw markdown; use it as-is.
        return text
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str):
            return content
    return ""


def _sanitize_argv(argv: list[str]) -> str:
    # Collapse the resolved binary path to its basename so the local home path
    # (and OS username) never lands in committed evidence.
    parts = list(argv)
    if parts:
        parts[0] = os.path.basename(parts[0])
    return sanitize_agent_reach_text(" ".join(parts))


def _shortcode(url: str) -> str | None:
    match = re.search(r"/(?:p|reel|tv)/([^/?#]+)", url)
    return match.group(1) if match else None


def parse_instagram_markdown(
    markdown: str,
    url: str,
    *,
    known_shortcode: str | None = None,
) -> ParsedInstagramPost:
    """Best-effort scrape of author / caption / counts / date from the Markdown.

    This is intentionally conservative: every field is optional and any field it
    cannot confidently recover is left ``None`` with a note appended, so the
    caller can degrade to a partial (metadata-only) record instead of emitting
    fabricated structured data.
    """

    text = markdown or ""
    shortcode = known_shortcode or _shortcode(url)
    fields_found: list[str] = []
    notes: list[str] = []

    author = None
    media_type = None
    display_date = None
    canonical_url = None

    # The canonical date link is the most reliable anchor: it embeds the author,
    # the post type (reel/p/tv) and the known shortcode, e.g.
    #   [April 5](/brycenwood.ai/reel/DWxmSwTDFk2/)
    if shortcode:
        canon = re.search(
            r"\[([^\]]+)\]\(/(" + _USERNAME + r")/(reel|p|tv)/" + re.escape(shortcode) + r"/\)",
            text,
        )
        if canon:
            display_date = canon.group(1).strip() or None
            author = canon.group(2)
            media_type = canon.group(3)
            canonical_url = f"https://www.instagram.com/{author}/{media_type}/{shortcode}/"
            fields_found.append("canonical_url")
            if display_date:
                fields_found.append("display_date")

    if author is None:
        # Fallback: first standalone username profile link.
        first_link = re.search(r"\]\(/(" + _USERNAME + r")/\)", text)
        if first_link:
            author = first_link.group(1)
            notes.append("author recovered from first profile link, not canonical anchor")
    if author:
        fields_found.append("author")

    # Relative time marker that immediately follows the author's link, e.g.
    #   ](/brycenwood.ai/)\n\n Edited•14w
    if author:
        rel = re.search(
            r"\]\(/" + re.escape(author) + r"/\)\s*(?:Edited\s*)?[•·]?\s*"
            r"(\d+\s*[a-z]+)\b",
            text,
        )
        if rel:
            relative_time = re.sub(r"\s+", "", rel.group(1))
            fields_found.append("relative_time")
        else:
            relative_time = None
    else:
        relative_time = None

    caption = _parse_caption(text, author)
    if caption:
        fields_found.append("caption")
    else:
        notes.append("caption not confidently isolated from rendered markdown")

    like_display, comment_display, count_note = _parse_counts(text, author, shortcode)
    if like_display:
        fields_found.append("like_count")
    if comment_display:
        fields_found.append("comment_count")
    if count_note:
        notes.append(count_note)

    if canonical_url is None:
        notes.append("canonical url not found; falling back to normalized /p/ form")

    return ParsedInstagramPost(
        author=author,
        caption=caption,
        like_count_display=like_display,
        comment_count_display=comment_display,
        display_date=display_date,
        relative_time=relative_time,
        media_type=media_type,
        canonical_url=canonical_url,
        fields_found=fields_found,
        notes=notes,
    )


def _parse_caption(text: str, author: str | None) -> str | None:
    if not author:
        return None
    # Caption sits between the author's time marker and the first structural
    # boundary that follows it: a comment/media avatar (`[![`), the like/comment
    # counts line, or the canonical date link back to the author's post. Hashtag
    # links inside the caption are `[#tag](...)`, never `[![`, so they survive.
    anchor = re.search(
        r"\]\(/" + re.escape(author) + r"/\)\s*(?:Edited\s*)?[•·]?\s*\d+\s*[a-z]+\s*\n",
        text,
    )
    if not anchor:
        return None
    rest = text[anchor.end() :]
    boundaries: list[int] = []
    for pattern in (
        r"\[!\[",  # comment / media avatar image
        r"\n\s*\d[\d.,]*[KMB]?\s*\n",  # like/comment counts line
        r"\[[^\]]*\]\(/" + _USERNAME + r"/(?:reel|p|tv)/",  # canonical date link
    ):
        hit = re.search(pattern, rest)
        if hit:
            boundaries.append(hit.start())
    cut = min(boundaries) if boundaries else len(rest)
    return _clean_caption(rest[:cut])


def _clean_caption(raw: str) -> str | None:
    # Collapse hashtag / mention markdown links to their visible text.
    cleaned = re.sub(r"\[(#[^\]]+)\]\([^)]*\)", r"\1", raw)
    cleaned = re.sub(r"\[(@[^\]]+)\]\([^)]*\)", r"\1", cleaned)
    # Drop any residual markdown image tokens.
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", cleaned)
    # Drop residual bare markdown links, keeping their visible text.
    cleaned = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _parse_counts(
    text: str,
    author: str | None,
    shortcode: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Recover like / comment display strings from the concatenated count blob.

    Reels render the like and comment totals concatenated with no separator
    directly above the canonical date link, e.g.::

        57.7K13.6K
        525
        [April 5](/brycenwood.ai/reel/DWxmSwTDFk2/)

    This is only recoverable when both values carry a K/M/B suffix. It is
    anchored tightly to the date-link position so it never grabs an unrelated
    number elsewhere on the page. Feed photo (`/p/`) posts render likes as
    separate "N likes" text and have no such blob, so we return ``None`` and a
    note instead of emitting a wrong value.
    """

    if not (author and shortcode):
        return None, None, "like/comment counts not parsed (missing author/shortcode anchor)"
    match = re.search(
        r"(\d[\d.,]*[KMB])(\d[\d.,]*[KMB])\s*\n+(?:\s*[\d.,]+[KMB]?\s*\n+)?\s*"
        r"\[[^\]]*\]\(/" + re.escape(author) + r"/(?:reel|p|tv)/" + re.escape(shortcode) + r"/\)",
        text,
    )
    if match:
        return match.group(1), match.group(2), None
    return (
        None,
        None,
        "like/comment counts not shown in a parseable concatenated form (non-reel or hidden)",
    )
