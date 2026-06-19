from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import httpx
import yt_dlp

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


def normalize_subtitle_text(subtitle: str) -> str:
    stripped = subtitle.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(subtitle)
            parts: list[str] = []
            for event in payload.get("events", []):
                for segment in event.get("segs", []) or []:
                    text = segment.get("utf8")
                    if text:
                        parts.append(text)
            return _collapse_caption_lines(parts)
        except json.JSONDecodeError:
            pass

    lines: list[str] = []
    for raw_line in subtitle.splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue
        if (
            line.upper().startswith("WEBVTT")
            or line.startswith("Kind:")
            or line.startswith("Language:")
        ):
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{\\.*?\}", "", line)
        line = line.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return _collapse_caption_lines(lines)


def _collapse_caption_lines(lines: list[str]) -> str:
    output: list[str] = []
    previous = ""
    for line in lines:
        cleaned = re.sub(r"\s+", " ", line).strip()
        if cleaned and cleaned != previous:
            output.append(cleaned)
            previous = cleaned
    text = " ".join(output)
    return re.sub(r"\s+", " ", text).strip()


def _upload_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        return value


class YouTubeExtractor:
    selected_strategy = "YouTubeExtractor"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, context: ExtractionContext) -> ExtractorResult:
        raw_item_dir = context.raw_dir / context.item_id if context.raw_dir else None
        with Timer() as timer:
            try:
                options = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "noplaylist": True,
                    "extract_flat": False,
                }
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(context.url, download=False)
                transcript_text, subtitle_source, subtitle_error = self._fetch_transcript(info)
                result = self.map_info_to_result(
                    context.url,
                    info,
                    transcript_text=transcript_text,
                    subtitle_source=subtitle_source,
                )
                if subtitle_error and result.extraction_status != "success":
                    result.metadata["subtitle_error"] = subtitle_error
                if raw_item_dir:
                    safe_metadata = self._safe_metadata(info)
                    write_json(raw_item_dir / "youtube_metadata.json", safe_metadata)
                    result.raw_artifacts["youtube_metadata"] = str(
                        raw_item_dir / "youtube_metadata.json"
                    )
                    if transcript_text:
                        write_text(raw_item_dir / "youtube_transcript.txt", transcript_text)
                        result.raw_artifacts["youtube_transcript"] = str(
                            raw_item_dir / "youtube_transcript.txt"
                        )
                result.latency_ms = timer.elapsed_ms
                return result
            except Exception as exc:  # noqa: BLE001 - extraction failures must be visible
                message = sanitize_error(exc)
                if raw_item_dir:
                    write_json(
                        raw_item_dir / "youtube_error.json",
                        {"url": context.url, "error": message},
                    )
                return ExtractorResult(
                    canonical_url=context.url,
                    source_type="youtube",
                    selected_strategy=self.selected_strategy,
                    extraction_status="failed",
                    error_code="youtube_extraction_failed",
                    error_message=message,
                    latency_ms=timer.elapsed_ms,
                )

    def map_info_to_result(
        self,
        url: str,
        info: dict[str, Any],
        *,
        transcript_text: str | None = None,
        subtitle_source: str | None = None,
    ) -> ExtractorResult:
        text = transcript_text.strip() if transcript_text else None
        status = "success" if text else "metadata_only"
        metadata = {
            "availability": info.get("availability"),
            "tags": info.get("tags") or [],
            "categories": info.get("categories") or [],
            "webpage_url": info.get("webpage_url") or url,
            "subtitle_source": subtitle_source,
            "human_subtitle_languages": sorted((info.get("subtitles") or {}).keys()),
            "automatic_subtitle_languages": sorted((info.get("automatic_captions") or {}).keys()),
        }
        return ExtractorResult(
            canonical_url=info.get("webpage_url") or url,
            source_type="youtube",
            selected_strategy=self.selected_strategy,
            extraction_status=status,
            title=info.get("title"),
            creator_or_author=info.get("uploader") or info.get("channel"),
            published_at=_upload_date(info.get("upload_date")),
            duration_seconds=info.get("duration"),
            description=info.get("description"),
            extracted_text=text,
            text_available=bool(text),
            content_hash=content_hash(text or info.get("description")),
            metadata=metadata,
        )

    def _fetch_transcript(self, info: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
        candidate = self._select_subtitle(info.get("subtitles") or {})
        source_type = "human"
        if candidate is None:
            candidate = self._select_subtitle(info.get("automatic_captions") or {})
            source_type = "automatic"
        if candidate is None:
            return None, None, None
        try:
            text = self._fetch_subtitle_url(candidate["url"])
            normalized = normalize_subtitle_text(text)
            if normalized:
                return normalized, f"{source_type}:{candidate.get('language', 'en')}", None
            return None, None, "subtitle_empty_after_normalization"
        except Exception as exc:  # noqa: BLE001
            return None, None, sanitize_error(exc)

    def _select_subtitle(self, subtitles: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
        language_keys = [key for key in subtitles if key == "en"] + [
            key for key in subtitles if key.startswith("en") and key != "en"
        ]
        for language in language_keys:
            entries = subtitles.get(language) or []
            for preferred_ext in ("vtt", "srt", "json3"):
                for entry in entries:
                    if entry.get("url") and entry.get("ext") == preferred_ext:
                        selected = dict(entry)
                        selected["language"] = language
                        return selected
            for entry in entries:
                if entry.get("url"):
                    selected = dict(entry)
                    selected["language"] = language
                    return selected
        return None

    def _fetch_subtitle_url(self, url: str) -> str:
        with httpx.Client(
            timeout=self.settings.http_timeout_seconds,
            follow_redirects=True,
            max_redirects=self.settings.http_max_redirects,
            headers={"User-Agent": self.settings.user_agent},
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.settings.http_max_bytes:
                        raise ValueError("subtitle exceeded configured byte limit")
                    chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _safe_metadata(self, info: dict[str, Any]) -> dict[str, Any]:
        keys = [
            "id",
            "title",
            "uploader",
            "channel",
            "description",
            "upload_date",
            "duration",
            "tags",
            "categories",
            "webpage_url",
            "availability",
            "subtitles",
            "automatic_captions",
        ]
        payload = {key: info.get(key) for key in keys if key in info}
        if payload.get("description") and len(payload["description"]) > 4000:
            payload["description"] = payload["description"][:4000] + "...<truncated>"
        return payload
