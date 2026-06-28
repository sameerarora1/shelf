from __future__ import annotations

import csv
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shelf.analysis.base import AnalyzerBackend
from shelf.analysis.deterministic import DeterministicAnalyzer
from shelf.config import Settings
from shelf.decision_policy import UrlDecision, classify_url
from shelf.extractors.base import ExtractionContext, ExtractorResult
from shelf.extractors.public_metadata import PublicMetadataExtractor
from shelf.extractors.unsupported import UnsupportedExtractor
from shelf.extractors.webpage import WebPageExtractor
from shelf.extractors.youtube import YouTubeExtractor
from shelf.models import SavedItem, TraceEvent
from shelf.organization.organizer import Organizer
from shelf.trace import Timer, TraceRecorder


@dataclass(frozen=True)
class PipelineResult:
    items: list[SavedItem]
    traces: list[TraceEvent]


class ShelfPipeline:
    def __init__(
        self,
        settings: Settings,
        *,
        analyzer: AnalyzerBackend | None = None,
        organizer: Organizer | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.analyzer = analyzer or DeterministicAnalyzer()
        self.organizer = organizer or Organizer()
        self.progress = progress

    def run_csv(self, input_csv: Path, *, raw_dir: Path | None = None) -> PipelineResult:
        rows = read_url_rows(input_csv)
        recorder = TraceRecorder()
        items: list[SavedItem] = []
        total = len(rows)
        for index, row in enumerate(rows, start=1):
            item = self.process_row(
                row,
                recorder=recorder,
                raw_dir=raw_dir,
                item_index=index,
                total_items=total,
            )
            items.append(item)
        return PipelineResult(items=items, traces=recorder.events)

    def process_row(
        self,
        row: dict[str, str],
        *,
        recorder: TraceRecorder,
        raw_dir: Path | None = None,
        item_index: int | None = None,
        total_items: int | None = None,
    ) -> SavedItem:
        item_id = row.get("item_id") or _stable_item_id(row.get("url", ""))
        url = row.get("url", "").strip()
        theme_hint = row.get("theme_hint", "").strip()
        trace_id = str(uuid.uuid4())
        progress_prefix = _progress_prefix(item_id, item_index, total_items)

        self._progress(f"{progress_prefix}: triaging")
        with Timer() as timer:
            decision = classify_url(url)
        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="triage",
            action="classify_url",
            decision=decision.decision,
            reason=decision.reason,
            tool="decision_policy.classify_url",
            status="ok" if decision.safe else "rejected",
            input_summary=url,
            output_summary=decision.source_type,
            duration_ms=timer.duration_ms,
            error_code=decision.error_code,
        )

        extractor = self._extractor_for_decision(decision)
        self._progress(
            f"{progress_prefix}: extracting with {type(extractor).__name__} "
            f"({decision.source_type})"
        )
        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="strategy_selection",
            action="select_extractor",
            decision=decision.selected_strategy,
            reason=decision.reason,
            tool="ShelfPipeline._extractor_for_decision",
            status="ok" if decision.safe else "rejected",
            input_summary=decision.source_type,
            output_summary=decision.selected_strategy,
            error_code=decision.error_code,
        )

        result = self._extract(item_id, url, extractor, recorder, trace_id, raw_dir)
        self._record_validation(result, item_id, trace_id, recorder)
        if result.extraction_status in {
            "metadata_only",
            "blocked",
            "failed",
            "unsupported",
            "rejected",
        }:
            recorder.record(
                trace_id=trace_id,
                item_id=item_id,
                stage="fallback",
                action="safe_fallback",
                decision=result.extraction_status,
                reason="Pipeline preserves a normalized record even when full text is unavailable.",
                tool="ShelfPipeline",
                status=result.extraction_status,
                input_summary=result.error_message,
                output_summary="normalized fallback record",
                error_code=result.error_code,
            )

        item = self._saved_item_from_result(
            item_id=item_id,
            url=url,
            theme_hint=theme_hint,
            trace_id=trace_id,
            result=result,
        )

        with Timer() as timer:
            self._progress(f"{progress_prefix}: analyzing with {type(self.analyzer).__name__}")
            analysis = self.analyzer.analyze(item, self.organizer.category_context())
        item.summary = analysis.summary
        item.topics = analysis.topics
        item.entities = analysis.entities
        item.content_type = analysis.content_type
        item.intent_tags = analysis.intent_tags
        item.analysis_mode = analysis.analysis_mode
        item.collection = analysis.suggested_collection
        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="analysis",
            action="analyze_content",
            decision=analysis.analysis_mode,
            reason="Analyzer produced summary, topics, entities, content type, and intent tags.",
            tool=type(self.analyzer).__name__,
            status="ok",
            input_summary=f"text_available={item.text_available}",
            output_summary=f"topics={','.join(item.topics[:5])}",
            duration_ms=timer.duration_ms,
        )

        with Timer() as timer:
            self._progress(f"{progress_prefix}: assigning collection")
            org_decision = self.organizer.assign(item, analysis)
        item.collection = org_decision.collection
        self._progress(f"{progress_prefix}: assigned {item.collection}")
        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="organization",
            action="assign_collection",
            decision=org_decision.collection,
            reason=org_decision.reason,
            tool=type(self.organizer).__name__,
            status="ok",
            input_summary=f"topics={item.topics}; intents={item.intent_tags}",
            output_summary=org_decision.collection,
            duration_ms=timer.duration_ms,
        )

        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="indexing",
            action="prepare_document",
            decision="included",
            reason="Item is eligible for the TF-IDF retrieval corpus using normalized fields.",
            tool="TfidfSearchIndex",
            status="ok",
            input_summary=item.item_id,
            output_summary="queued for indexing",
        )
        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="persistence",
            action="persist_normalized_item",
            decision="upsert",
            reason="Normalized item and trace are written to SQLite and evidence artifacts.",
            tool="SQLiteStore",
            status="pending",
            input_summary=item.item_id,
            output_summary="pending store write",
        )
        return item

    def _progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(f"Progress: {message}")

    def _extract(
        self,
        item_id: str,
        url: str,
        extractor: object,
        recorder: TraceRecorder,
        trace_id: str,
        raw_dir: Path | None,
    ) -> ExtractorResult:
        with Timer() as timer:
            result = extractor.extract(ExtractionContext(item_id=item_id, url=url, raw_dir=raw_dir))
        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="extraction",
            action="extract",
            decision=result.extraction_status,
            reason="Extractor returned a structured result; failures are preserved on the item.",
            tool=type(extractor).__name__,
            status=result.extraction_status,
            input_summary=url,
            output_summary=f"title={result.title!r}; chars={result.text_character_count}",
            duration_ms=result.latency_ms or timer.duration_ms,
            error_code=result.error_code,
        )
        return result

    def _record_validation(
        self,
        result: ExtractorResult,
        item_id: str,
        trace_id: str,
        recorder: TraceRecorder,
    ) -> None:
        valid, reason = validate_extraction_result(result)
        recorder.record(
            trace_id=trace_id,
            item_id=item_id,
            stage="validation",
            action="validate_extraction_result",
            decision="valid" if valid else "fallback_required",
            reason=reason,
            tool="validate_extraction_result",
            status="ok" if valid else result.extraction_status,
            input_summary=result.extraction_status,
            output_summary=f"text_available={result.text_available}",
            error_code=result.error_code,
        )

    def _extractor_for_decision(self, decision: UrlDecision) -> object:
        if not decision.safe:
            return UnsupportedExtractor(
                reason=decision.reason,
                error_code=decision.error_code or "unsafe_url",
            )
        if decision.source_type == "youtube":
            return YouTubeExtractor(self.settings)
        if decision.source_type == "public_webpage":
            return WebPageExtractor(self.settings)
        if decision.source_type in {"instagram_public", "x_public"}:
            return PublicMetadataExtractor(self.settings, decision.source_type)
        return UnsupportedExtractor(reason=decision.reason)

    def _saved_item_from_result(
        self,
        *,
        item_id: str,
        url: str,
        theme_hint: str,
        trace_id: str,
        result: ExtractorResult,
    ) -> SavedItem:
        return SavedItem(
            item_id=item_id,
            url=url,
            canonical_url=result.canonical_url,
            source_type=result.source_type,
            theme_hint=theme_hint,
            selected_strategy=result.selected_strategy,
            extraction_status=result.extraction_status,
            title=result.title,
            creator_or_author=result.creator_or_author,
            published_at=result.published_at,
            duration_seconds=result.duration_seconds,
            description=result.description,
            extracted_text=result.extracted_text,
            text_available=result.text_available,
            text_character_count=result.text_character_count,
            content_hash=result.content_hash,
            analysis_mode=getattr(self.analyzer, "mode", "deterministic"),
            trace_id=trace_id,
            error_code=result.error_code,
            error_message=result.error_message,
            latency_ms=result.latency_ms,
        )


def validate_extraction_result(result: ExtractorResult) -> tuple[bool, str]:
    if (
        result.extraction_status == "success"
        and result.text_available
        and result.text_character_count > 0
    ):
        return True, "Extracted text is available and non-empty."
    if result.extraction_status == "metadata_only" and (result.title or result.description):
        return True, "No body text was available, but public metadata was captured."
    if result.extraction_status in {"blocked", "unsupported", "failed", "rejected"}:
        return False, f"Extractor status is {result.extraction_status}; fallback record required."
    return False, "Result did not meet text or metadata validation requirements."


def read_url_rows(input_csv: Path) -> list[dict[str, str]]:
    with input_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"item_id", "url", "theme_hint", "notes"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Input CSV missing required columns: {sorted(missing)}")
        return [dict(row) for row in reader if row.get("url")]


def input_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_item_id(url: str) -> str:
    return "item_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def _progress_prefix(item_id: str, item_index: int | None, total_items: int | None) -> str:
    if item_index is None or total_items is None:
        return item_id
    return f"[{item_index}/{total_items}] {item_id}"
