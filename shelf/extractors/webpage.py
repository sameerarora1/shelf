from __future__ import annotations

import re
from typing import Any

import httpx
import trafilatura

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


class WebPageExtractor:
    selected_strategy = "WebPageExtractor"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, context: ExtractionContext) -> ExtractorResult:
        raw_item_dir = context.raw_dir / context.item_id if context.raw_dir else None
        with Timer() as timer:
            try:
                response_url, headers, html = self._fetch_html(context.url)
                result = self.map_html_to_result(context.url, response_url, headers, html)
                if raw_item_dir:
                    metadata = {
                        "requested_url": context.url,
                        "final_url": response_url,
                        "headers": {
                            "content-type": headers.get("content-type"),
                            "content-length": headers.get("content-length"),
                            "etag": headers.get("etag"),
                            "last-modified": headers.get("last-modified"),
                        },
                        "trafilatura_metadata": result.metadata,
                    }
                    write_json(raw_item_dir / "web_response_metadata.json", metadata)
                    write_text(
                        raw_item_dir / "web_raw_limited.html",
                        html[: self.settings.raw_html_max_chars],
                    )
                    if result.extracted_text:
                        write_text(raw_item_dir / "web_extracted_text.txt", result.extracted_text)
                    result.raw_artifacts["web_response_metadata"] = str(
                        raw_item_dir / "web_response_metadata.json"
                    )
                    result.raw_artifacts["web_raw_limited"] = str(
                        raw_item_dir / "web_raw_limited.html"
                    )
                result.latency_ms = timer.elapsed_ms
                return result
            except Exception as exc:  # noqa: BLE001
                message = sanitize_error(exc)
                if raw_item_dir:
                    write_json(
                        raw_item_dir / "web_error.json",
                        {"url": context.url, "error": message},
                    )
                status = "blocked" if isinstance(exc, httpx.HTTPStatusError) else "failed"
                return ExtractorResult(
                    canonical_url=context.url,
                    source_type="public_webpage",
                    selected_strategy=self.selected_strategy,
                    extraction_status=status,
                    error_code="webpage_extraction_failed",
                    error_message=message,
                    latency_ms=timer.elapsed_ms,
                )

    def _fetch_html(self, url: str) -> tuple[str, httpx.Headers, str]:
        with httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            max_redirects=self.settings.http_max_redirects,
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "html" not in content_type and "text/plain" not in content_type:
                    raise ValueError(
                        f"Unsupported content type for webpage extraction: {content_type}"
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.settings.http_max_bytes:
                        raise ValueError("response exceeded configured byte limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                html = body.decode(encoding, errors="replace")
                return str(response.url), response.headers, html

    def map_html_to_result(
        self,
        requested_url: str,
        final_url: str,
        headers: httpx.Headers | dict[str, str],
        html: str,
    ) -> ExtractorResult:
        metadata_obj = trafilatura.extract_metadata(html)
        metadata: dict[str, Any] = metadata_obj.as_dict() if metadata_obj else {}
        extracted = trafilatura.extract(
            html,
            url=final_url,
            output_format="txt",
            include_comments=False,
            include_tables=True,
        )
        fallback_title = _extract_title(html)
        fallback_description = _extract_meta_description(html)
        text = (extracted or "").strip() or None
        title = metadata.get("title") or fallback_title
        author = metadata.get("author")
        published = metadata.get("date")
        description = metadata.get("description") or fallback_description
        status = "success" if text else "metadata_only"
        return ExtractorResult(
            canonical_url=metadata.get("url") or final_url or requested_url,
            source_type="public_webpage",
            selected_strategy=self.selected_strategy,
            extraction_status=status,
            title=title,
            creator_or_author=author,
            published_at=published,
            description=description,
            extracted_text=text,
            text_available=bool(text),
            content_hash=content_hash(text or description),
            metadata={
                "content_type": headers.get("content-type") if hasattr(headers, "get") else None,
                "trafilatura": metadata,
            },
        )


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _extract_meta_description(html: str) -> str | None:
    match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html,
        flags=re.I | re.S,
    )
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()
