from __future__ import annotations

import re

import httpx

from shelf.config import Settings
from shelf.extractors.base import (
    ExtractionContext,
    ExtractorResult,
    content_hash,
    sanitize_error,
    write_json,
    write_text,
)
from shelf.trace import Timer


class PublicMetadataExtractor:
    selected_strategy = "PublicMetadataExtractor"

    def __init__(self, settings: Settings, source_type: str) -> None:
        self.settings = settings
        self.source_type = source_type

    def extract(self, context: ExtractionContext) -> ExtractorResult:
        raw_item_dir = context.raw_dir / context.item_id if context.raw_dir else None
        with Timer() as timer:
            try:
                final_url, headers, html = self._fetch_public_html(context.url)
                title = _extract_title(html)
                description = _extract_meta_description(html)
                if raw_item_dir:
                    write_json(
                        raw_item_dir / "public_metadata_response.json",
                        {
                            "requested_url": context.url,
                            "final_url": final_url,
                            "content_type": headers.get("content-type"),
                            "content_length": headers.get("content-length"),
                            "title": title,
                            "description": description,
                        },
                    )
                    write_text(raw_item_dir / "public_metadata_raw_limited.html", html[:20_000])
                status = "metadata_only" if title or description else "blocked"
                return ExtractorResult(
                    canonical_url=final_url,
                    source_type=self.source_type,  # type: ignore[arg-type]
                    selected_strategy=self.selected_strategy,
                    extraction_status=status,
                    title=title,
                    description=description,
                    extracted_text=None,
                    text_available=False,
                    content_hash=content_hash(f"{title or ''}\n{description or ''}"),
                    latency_ms=timer.elapsed_ms,
                    error_code=None if status == "metadata_only" else "metadata_unavailable",
                    error_message=None
                    if status == "metadata_only"
                    else "Public metadata was not available without authenticated access.",
                )
            except Exception as exc:  # noqa: BLE001
                message = sanitize_error(exc)
                if raw_item_dir:
                    write_json(
                        raw_item_dir / "public_metadata_error.json",
                        {"url": context.url, "error": message},
                    )
                return ExtractorResult(
                    canonical_url=context.url,
                    source_type=self.source_type,  # type: ignore[arg-type]
                    selected_strategy=self.selected_strategy,
                    extraction_status="blocked",
                    error_code="public_metadata_blocked",
                    error_message=message,
                    latency_ms=timer.elapsed_ms,
                )

    def _fetch_public_html(self, url: str) -> tuple[str, httpx.Headers, str]:
        with httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            max_redirects=self.settings.http_max_redirects,
            headers={"User-Agent": self.settings.user_agent, "Accept": "text/html"},
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > min(self.settings.http_max_bytes, 500_000):
                        raise ValueError("metadata response exceeded configured byte limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
        return (
            str(response.url),
            response.headers,
            body.decode(response.encoding or "utf-8", "replace"),
        )


def _extract_title(html: str) -> str | None:
    og = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        html,
        flags=re.I | re.S,
    )
    if og:
        return re.sub(r"\s+", " ", og.group(1)).strip()
    title = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if title:
        return re.sub(r"\s+", " ", title.group(1)).strip()
    return None


def _extract_meta_description(html: str) -> str | None:
    for pattern in (
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    ):
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return None
