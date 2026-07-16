from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from shelf.config import Settings
from shelf.extractors.agent_reach import sanitize_agent_reach_text
from shelf.extractors.base import (
    ExtractionContext,
    ExtractorResult,
    content_hash,
    write_json,
    write_text,
)
from shelf.extractors.opencli import (
    OpenCliDoctorResult,
    OpenCliInstagramRunner,
    OpenCliPostRead,
    ParsedInstagramPost,
    parse_instagram_markdown,
)
from shelf.extractors.public_metadata import PublicMetadataExtractor
from shelf.trace import Timer


class InstagramPostExtractor:
    """Reads Instagram ``/p/`` and ``/reel/`` posts via the opencli browser bridge.

    Tiered behaviour:

    1. opencli browser open+extract, then a best-effort Markdown parse into
       structured fields (author, caption, counts, date). A caption yields a
       ``success`` record; a partial parse (some fields, no caption) yields a
       traceable ``metadata_only`` record rather than fabricated data.
    2. If opencli is unavailable, the session is not logged in, or the browser
       read/parse fails, fall back to the existing public-metadata extractor and
       record a structured failure reason.
    """

    selected_strategy = "InstagramPostExtractor"

    def __init__(
        self,
        settings: Settings,
        *,
        runner: OpenCliInstagramRunner | None = None,
        metadata_extractor: PublicMetadataExtractor | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or OpenCliInstagramRunner(
            settings.opencli_timeout_seconds,
            binary=settings.opencli_bin,
            session_name=settings.opencli_instagram_session,
            window_mode=settings.opencli_browser_window,
        )
        self.metadata_extractor = metadata_extractor or PublicMetadataExtractor(
            settings,
            "instagram_public",
        )

    def extract(self, context: ExtractionContext) -> ExtractorResult:
        raw_item_dir = context.raw_dir / context.item_id if context.raw_dir else None
        with Timer() as timer:
            doctor = self.runner.doctor()
            failure_code: str
            failure_message: str
            if doctor.available:
                read = self.runner.read_post(context.url)
                if read.ok and read.markdown:
                    parsed = parse_instagram_markdown(
                        read.markdown,
                        context.url,
                        known_shortcode=_shortcode(context.url),
                    )
                    if parsed.has_any_field:
                        result = self.map_parsed_post_to_result(context.url, parsed)
                        result.latency_ms = timer.elapsed_ms
                        if raw_item_dir:
                            _write_success_evidence(raw_item_dir, doctor, read, parsed, result)
                        return result
                    # A page loaded but nothing parsed: prefer the richer public
                    # metadata fallback over an empty structured record.
                    failure_code = "opencli_instagram_empty"
                    failure_message = (
                        "opencli returned a page but no Instagram post fields could be parsed."
                    )
                    if raw_item_dir:
                        _write_failure_evidence(raw_item_dir, doctor, read, failure_message)
                else:
                    failure_code = read.error_code or "opencli_instagram_read_failed"
                    failure_message = (
                        read.error_message or "opencli browser read of the Instagram post failed."
                    )
                    if raw_item_dir:
                        _write_failure_evidence(raw_item_dir, doctor, read, failure_message)
            else:
                failure_code = doctor.error_code or "opencli_instagram_unavailable"
                failure_message = (
                    doctor.error_message or "opencli Instagram access is unavailable."
                )
                if raw_item_dir:
                    _write_failure_evidence(raw_item_dir, doctor, None, failure_message)

            fallback = self.metadata_extractor.extract(context)
            fallback.selected_strategy = self.selected_strategy
            fallback.source_type = "instagram_public"
            fallback.latency_ms = timer.elapsed_ms
            fallback.error_code = fallback.error_code or failure_code
            fallback.error_message = _combine_failure_messages(failure_message, fallback)
            fallback.metadata["opencli_fallback_reason"] = failure_message
            fallback.metadata["opencli_error_code"] = failure_code
            return fallback

    def map_parsed_post_to_result(
        self,
        url: str,
        parsed: ParsedInstagramPost,
    ) -> ExtractorResult:
        caption = parsed.caption
        author = parsed.author
        canonical_url = parsed.canonical_url or _canonical_ig_url(url)
        title = _title(author, caption, url)
        status = "success" if caption else "metadata_only"
        has_signal = bool(caption or author or parsed.has_any_field)
        error_code = None
        error_message = None
        if not caption and has_signal:
            error_code = "opencli_instagram_partial"
            error_message = (
                "opencli returned a post page but the caption could not be isolated; "
                "emitted a partial metadata-only record. "
                f"Parsed fields: {', '.join(parsed.fields_found) or 'none'}."
            )
        elif not has_signal:
            error_code = "opencli_instagram_empty"
            error_message = "opencli returned a page with no recoverable Instagram post fields."
        return ExtractorResult(
            canonical_url=canonical_url,
            source_type="instagram_public",
            selected_strategy=self.selected_strategy,
            extraction_status=status,
            title=title,
            creator_or_author=author,
            published_at=parsed.display_date,
            description=caption,
            extracted_text=caption,
            text_available=bool(caption),
            content_hash=content_hash(caption or title),
            error_code=error_code,
            error_message=error_message,
            metadata={
                "platform": "instagram",
                "backend": "opencli",
                "shortcode": _shortcode(url),
                "media_type": parsed.media_type,
                "relative_time": parsed.relative_time,
                "like_count_display": parsed.like_count_display,
                "comment_count_display": parsed.comment_count_display,
                "parse_fields_found": parsed.fields_found,
                "parse_notes": parsed.notes,
            },
        )


def _write_success_evidence(
    raw_item_dir: Path,
    doctor: OpenCliDoctorResult,
    read: OpenCliPostRead,
    parsed: ParsedInstagramPost,
    result: ExtractorResult,
) -> None:
    write_json(
        raw_item_dir / "instagram_opencli_response.json",
        {
            # Boolean only: never persist the logged-in account identity.
            "logged_in": doctor.session_active,
            "backend": "opencli",
            "commands": [sanitize_agent_reach_text(cmd) for cmd in read.argv_log],
            "returncode": read.returncode,
            "extraction_status": result.extraction_status,
            # Public target-post fields (the account being looked at). These are
            # written as-is rather than through the key redactor, which would
            # scrub structural keys like `author` (contains "auth").
            "parsed": {
                "author": parsed.author,
                "caption": _sanitize_optional(parsed.caption),
                "display_date": parsed.display_date,
                "relative_time": parsed.relative_time,
                "media_type": parsed.media_type,
                "canonical_url": parsed.canonical_url,
                "like_count_display": parsed.like_count_display,
                "comment_count_display": parsed.comment_count_display,
                "fields_found": parsed.fields_found,
                "notes": parsed.notes,
            },
        },
    )
    if read.markdown:
        write_text(
            raw_item_dir / "instagram_opencli_markdown_limited.txt",
            sanitize_agent_reach_text(read.markdown),
        )


def _write_failure_evidence(
    raw_item_dir: Path,
    doctor: OpenCliDoctorResult,
    read: OpenCliPostRead | None = None,
    message: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "backend": "opencli",
        "logged_in": doctor.session_active,
        "doctor_error_code": doctor.error_code,
        "doctor_error_message": _sanitize_optional(doctor.error_message),
        "message": _sanitize_optional(message),
    }
    if read is not None:
        payload.update(
            {
                "commands": [sanitize_agent_reach_text(cmd) for cmd in read.argv_log],
                "returncode": read.returncode,
                "read_error_code": read.error_code,
                "read_error_message": _sanitize_optional(read.error_message),
            }
        )
    write_json(raw_item_dir / "instagram_opencli_error.json", payload)


def _sanitize_optional(text: str | None) -> str | None:
    return sanitize_agent_reach_text(text) if text else None


def _combine_failure_messages(reason: str, fallback: ExtractorResult) -> str:
    if fallback.error_message:
        return f"{reason} Public metadata fallback: {fallback.error_message}"
    return f"{reason} Public metadata fallback returned {fallback.extraction_status}."


def _title(author: str | None, caption: str | None, url: str) -> str | None:
    if author:
        return f"Instagram post by {author}"
    shortcode = _shortcode(url)
    if shortcode:
        return f"Instagram post {shortcode}"
    if caption:
        return caption[:117].rstrip() + "..." if len(caption) > 120 else caption
    return None


def _shortcode(url: str) -> str | None:
    match = re.search(r"/(?:p|reel|tv)/([^/?#]+)", url)
    return match.group(1) if match else None


def _canonical_ig_url(url: str) -> str:
    shortcode = _shortcode(url)
    if not shortcode:
        return url
    parsed = urlparse(url)
    host = parsed.hostname or "www.instagram.com"
    return f"https://{host}/p/{shortcode}/"
