"""Checkpoint 3 deliverable: analyzer comparison across backends.

Adapted from the professor's ``ai-suggestions/cp3`` reference harness. It
extracts the saved-item dataset exactly once (so extraction is held constant),
then re-runs each analyzer backend over the *same* :class:`SavedItem` records.
For every backend it reuses the existing acceptance evaluator
(:func:`shelf.analysis.evaluate.evaluate_analysis_quality`) and the labeled
retrieval evaluator (:func:`shelf.retrieval.evaluate.evaluate_queries`), and
measures per-item analyzer latency.

Adaptations over the reference:

* An explicit, honestly-labeled ``unavailable`` backend that wires the real
  :class:`OpenAIAnalyzer` to a stub client whose requests always fail, so the
  deterministic fallback path is *exercised and measured* rather than only
  described. This demonstrates fallback behavior for unavailable/invalid LLM
  output even when no API key is configured. It performs no network call and is
  never presented as real LLM output.
* Per-backend collection of acceptance failure reasons and analyzer fallback
  notes, so the comparison reports *why* a backend missed a dimension.
* A redacted configuration block (:meth:`Settings.redacted_config`) in the
  report, and retention of each backend's re-analyzed items for evidence
  persistence -- never the API key, ``.env`` contents, or request headers.

Every metric below is derived deterministically from analyzer outputs by the
existing evaluation code, never by the model itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from shelf.analysis.base import AnalyzerBackend
from shelf.analysis.deterministic import DeterministicAnalyzer
from shelf.analysis.evaluate import evaluate_analysis_quality
from shelf.analysis.openai_provider import OpenAIAnalyzer, OpenRouterConfigError
from shelf.config import Settings
from shelf.models import SavedItem, TraceEvent
from shelf.orchestrator import ShelfPipeline
from shelf.organization.organizer import Organizer
from shelf.retrieval.evaluate import evaluate_queries

DETERMINISTIC_SPECS = {"deterministic", "det", "baseline"}
UNAVAILABLE_SPECS = {"unavailable", "fallback", "offline"}
FREE_OPENROUTER_COMPARISON_MODELS = (
    "openrouter/free",
    "tencent/hy3:free",
    "poolside/laguna-m.1:free",
)
_UNAVAILABLE_MESSAGE = (
    "Simulated unavailable OpenRouter backend: no API call performed "
    "(offline / no-key fallback demonstration)."
)


class _UnavailableCompletions:
    def __init__(self, message: str) -> None:
        self._message = message

    def create(self, **kwargs: Any) -> Any:  # noqa: ANN401 - mirrors SDK signature
        raise RuntimeError(self._message)


class _UnavailableChat:
    def __init__(self, message: str) -> None:
        self.completions = _UnavailableCompletions(message)


class _UnavailableClient:
    """Stub OpenRouter client whose requests always fail.

    Wired into :class:`OpenAIAnalyzer` to exercise its deterministic fallback
    path as an explicit ``unavailable`` comparison backend. It performs no
    network call and is never presented as real LLM output.
    """

    def __init__(self, message: str = _UNAVAILABLE_MESSAGE) -> None:
        self.chat = _UnavailableChat(message)


@dataclass
class ModelComparison:
    """One row of the cross-analyzer comparison table."""

    spec: str
    analyzer_mode: str
    status: str = "evaluated"
    skip_reason: str | None = None
    item_count: int = 0
    analysis_modes: dict[str, int] = field(default_factory=dict)
    fallback_to_deterministic: int = 0
    structured_output_valid_rate: float = 0.0
    metadata_complete_rate: float = 0.0
    tag_agreement_rate: float = 0.0
    fallback_behavior_valid_rate: float = 0.0
    trace_coverage_rate: float = 0.0
    overall_pass_rate: float = 0.0
    retrieval_status: str = "not_evaluated"
    precision_at_3: float = 0.0
    mrr: float = 0.0
    evaluated_query_count: int = 0
    mean_analysis_latency_ms: float = 0.0
    max_analysis_latency_ms: float = 0.0
    failure_reasons: list[str] = field(default_factory=list)
    fallback_notes: list[str] = field(default_factory=list)
    # Re-analyzed records kept for evidence persistence; excluded from to_dict.
    reanalyzed_items: list[SavedItem] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "analyzer_mode": self.analyzer_mode,
            "status": self.status,
            "skip_reason": self.skip_reason,
            "item_count": self.item_count,
            "analysis_modes": self.analysis_modes,
            "fallback_to_deterministic": self.fallback_to_deterministic,
            "structured_output_valid_rate": self.structured_output_valid_rate,
            "metadata_complete_rate": self.metadata_complete_rate,
            "tag_agreement_rate": self.tag_agreement_rate,
            "fallback_behavior_valid_rate": self.fallback_behavior_valid_rate,
            "trace_coverage_rate": self.trace_coverage_rate,
            "overall_pass_rate": self.overall_pass_rate,
            "retrieval_status": self.retrieval_status,
            "precision_at_3": self.precision_at_3,
            "mrr": self.mrr,
            "evaluated_query_count": self.evaluated_query_count,
            "mean_analysis_latency_ms": self.mean_analysis_latency_ms,
            "max_analysis_latency_ms": self.max_analysis_latency_ms,
            "failure_reasons": self.failure_reasons,
            "fallback_notes": self.fallback_notes,
        }


@dataclass
class ComparisonRun:
    """Result of a full comparison: report plus rows and shared traces."""

    report: dict[str, Any]
    rows: list[ModelComparison]
    base_traces: list[TraceEvent]


def default_model_specs(settings: Settings) -> list[str]:
    """Return the reproducible default comparison matrix.

    The configured model remains part of the matrix so a user can evaluate a
    local default without editing code. The two additional free OpenRouter
    model IDs are explicit defaults for the checkpoint comparison, while the
    deterministic baseline and forced-unavailable backend keep quality and
    fallback behavior anchored even if provider access changes.
    """
    candidates = [
        "deterministic",
        settings.openrouter_model,
        *FREE_OPENROUTER_COMPARISON_MODELS,
        "unavailable",
    ]
    specs: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            specs.append(normalized)
            seen.add(key)
    return specs


def build_analyzer(spec: str, settings: Settings) -> AnalyzerBackend:
    """Resolve a comparison spec into a concrete analyzer backend.

    ``"deterministic"`` (and aliases) yields the deterministic baseline.
    ``"unavailable"`` (and aliases) yields the real :class:`OpenAIAnalyzer`
    wired to a stub client that always fails, exercising the deterministic
    fallback path with no network call. Any other spec is treated as an
    OpenRouter model id routed through :class:`OpenAIAnalyzer`, reusing the
    project's OpenRouter configuration.
    """
    key = spec.strip().lower()
    if key in DETERMINISTIC_SPECS:
        return DeterministicAnalyzer()
    if key in UNAVAILABLE_SPECS:
        return OpenAIAnalyzer(
            "unavailable-openrouter-backend",
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.openrouter_timeout_seconds,
            client=_UnavailableClient(),
        )
    return OpenAIAnalyzer(
        spec.strip(),
        base_url=settings.openrouter_base_url,
        timeout_seconds=settings.openrouter_timeout_seconds,
    )


def _reanalyze_item(
    base_item: SavedItem,
    analyzer: AnalyzerBackend,
    organizer: Organizer,
) -> tuple[SavedItem, float, list[str]]:
    """Re-run one analyzer over a copy of an already-extracted item.

    Mirrors the field mapping performed by
    :meth:`shelf.orchestrator.ShelfPipeline.process_row` so the re-analyzed
    record is comparable to a real pipeline run. Returns the updated item, the
    analyzer latency in milliseconds, and the analysis evidence notes.
    """
    item = base_item.model_copy(deep=True)
    start = time.perf_counter()
    analysis = analyzer.analyze(item, organizer.category_context())
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    item.summary = analysis.summary
    item.topics = analysis.topics
    item.entities = analysis.entities
    item.content_type = analysis.content_type
    item.intent_tags = analysis.intent_tags
    item.analysis_mode = analysis.analysis_mode
    item.collection = organizer.assign(item, analysis).collection
    return item, elapsed_ms, list(analysis.evidence_notes)


def compare_analyzer_backends(
    base_items: list[SavedItem],
    traces: list[TraceEvent],
    backends: list[tuple[str, AnalyzerBackend]],
    queries_csv: Path,
) -> list[ModelComparison]:
    """Evaluate each analyzer backend over the same extracted dataset.

    ``base_items`` are the shared, already-extracted records. Each backend is
    re-run over deep copies of those records, then scored with the existing
    acceptance and retrieval evaluators. ``traces`` are reused for trace
    coverage because extraction/orchestration stages are analyzer-independent.
    """
    rows: list[ModelComparison] = []
    for spec, analyzer in backends:
        organizer = Organizer()
        analyzer_mode = getattr(analyzer, "mode", "deterministic")
        reanalyzed: list[SavedItem] = []
        latencies: list[float] = []
        fallback_notes: set[str] = set()
        for base_item in base_items:
            item, elapsed_ms, notes = _reanalyze_item(base_item, analyzer, organizer)
            reanalyzed.append(item)
            latencies.append(elapsed_ms)
            if analyzer_mode != "deterministic" and item.analysis_mode == "deterministic":
                for note in notes:
                    lowered = note.lower()
                    if "fallback" in lowered or "failed" in lowered:
                        fallback_notes.add(note)

        analysis_metrics, analysis_details = evaluate_analysis_quality(reanalyzed, traces)
        retrieval_metrics, _ = evaluate_queries(reanalyzed, queries_csv)

        failure_reasons = sorted(
            {reason for detail in analysis_details for reason in detail["failure_reasons"]}
        )
        observed_modes: dict[str, int] = dict(analysis_metrics.get("analysis_modes", {}))
        fallback_hits = sum(
            1
            for item in reanalyzed
            if analyzer_mode != "deterministic" and item.analysis_mode == "deterministic"
        )
        rows.append(
            ModelComparison(
                spec=spec,
                analyzer_mode=analyzer_mode,
                status=(
                    "fallback_only"
                    if analyzer_mode != "deterministic" and fallback_hits == len(reanalyzed)
                    else "evaluated"
                ),
                item_count=analysis_metrics.get("item_count", len(reanalyzed)),
                analysis_modes=observed_modes,
                fallback_to_deterministic=fallback_hits,
                structured_output_valid_rate=analysis_metrics.get(
                    "structured_output_valid_rate", 0.0
                ),
                metadata_complete_rate=analysis_metrics.get("metadata_complete_rate", 0.0),
                tag_agreement_rate=analysis_metrics.get("tag_agreement_rate", 0.0),
                fallback_behavior_valid_rate=analysis_metrics.get(
                    "fallback_behavior_valid_rate", 0.0
                ),
                trace_coverage_rate=analysis_metrics.get("trace_coverage_rate", 0.0),
                overall_pass_rate=analysis_metrics.get("overall_pass_rate", 0.0),
                retrieval_status=retrieval_metrics.get("status", "not_evaluated"),
                precision_at_3=float(retrieval_metrics.get("precision_at_3", 0.0) or 0.0),
                mrr=float(retrieval_metrics.get("mrr", 0.0) or 0.0),
                evaluated_query_count=int(retrieval_metrics.get("evaluated_query_count", 0) or 0),
                mean_analysis_latency_ms=round(mean(latencies), 3) if latencies else 0.0,
                max_analysis_latency_ms=round(max(latencies), 3) if latencies else 0.0,
                failure_reasons=failure_reasons[:12],
                fallback_notes=sorted(fallback_notes)[:6],
                reanalyzed_items=reanalyzed,
            )
        )
    return rows


def run_comparison(
    settings: Settings,
    input_csv: Path,
    queries_csv: Path,
    model_specs: list[str],
    *,
    raw_dir: Path | None = None,
    progress: Any = None,
) -> ComparisonRun:
    """Extract the dataset once, then score every requested backend.

    Backends that cannot be configured (for example an OpenRouter model with no
    API key present) are reported as skipped rather than aborting the whole
    comparison. The returned :class:`ComparisonRun` carries the report, the
    per-backend rows (with their re-analyzed items), and the shared extraction
    traces so the caller can persist sanitized evidence.
    """
    base_result = ShelfPipeline(
        settings,
        analyzer=DeterministicAnalyzer(),
        organizer=Organizer(),
        progress=progress,
    ).run_csv(input_csv, raw_dir=raw_dir)

    backends: list[tuple[str, AnalyzerBackend]] = []
    skipped: list[ModelComparison] = []
    for spec in model_specs:
        try:
            backends.append((spec, build_analyzer(spec, settings)))
        except OpenRouterConfigError as exc:
            skipped.append(
                ModelComparison(
                    spec=spec,
                    analyzer_mode="openrouter",
                    status="skipped",
                    skip_reason=str(exc),
                )
            )

    evaluated = compare_analyzer_backends(
        base_result.items,
        base_result.traces,
        backends,
        queries_csv,
    )
    rows = evaluated + skipped
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(input_csv),
        "queries": str(queries_csv),
        "item_count": len(base_result.items),
        "trace_count": len(base_result.traces),
        "model_specs": list(model_specs),
        "config": settings.redacted_config(),
        "models": [row.to_dict() for row in rows],
        "leaderboard": _leaderboard(evaluated),
    }
    return ComparisonRun(report=report, rows=rows, base_traces=base_result.traces)


def compare_analyzers(
    settings: Settings,
    input_csv: Path,
    queries_csv: Path,
    model_specs: list[str],
    *,
    raw_dir: Path | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    """Convenience wrapper returning only the comparison report dict."""
    return run_comparison(
        settings,
        input_csv,
        queries_csv,
        model_specs,
        raw_dir=raw_dir,
        progress=progress,
    ).report


def _leaderboard(comparisons: list[ModelComparison]) -> dict[str, Any]:
    """Pick the strongest backend by acceptance pass-rate, then retrieval."""
    evaluated = [row for row in comparisons if row.status == "evaluated"]
    if not evaluated:
        return {
            "best_spec": None,
            "note": "No provider generated a usable LLM response; fallback-only rows are excluded.",
        }
    best = max(
        evaluated,
        key=lambda row: (row.overall_pass_rate, row.precision_at_3, row.mrr),
    )
    return {
        "best_spec": best.spec,
        "best_overall_pass_rate": best.overall_pass_rate,
        "best_precision_at_3": best.precision_at_3,
        "best_mrr": best.mrr,
    }


_MARKDOWN_COLUMNS = [
    ("spec", "Model / Backend"),
    ("status", "Status"),
    ("analyzer_mode", "Mode"),
    ("overall_pass_rate", "Accept Pass"),
    ("structured_output_valid_rate", "Struct OK"),
    ("tag_agreement_rate", "Tag Agree"),
    ("fallback_behavior_valid_rate", "Fallback OK"),
    ("precision_at_3", "P@3"),
    ("mrr", "MRR"),
    ("fallback_to_deterministic", "Fallbacks"),
    ("mean_analysis_latency_ms", "Mean ms"),
]


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render the comparison report as a Markdown document with a table."""
    lines: list[str] = []
    lines.append("# Checkpoint 3 - Analyzer Comparison Across Backends")
    lines.append("")
    lines.append(f"- Generated: `{report.get('generated_at', '')}`")
    lines.append(f"- Dataset: `{report.get('dataset', '')}`")
    lines.append(f"- Retrieval labels: `{report.get('queries', '')}`")
    lines.append(
        f"- Items: {report.get('item_count', 0)} | Traces: {report.get('trace_count', 0)}"
    )
    config = report.get("config") or {}
    if config:
        lines.append(
            f"- Analyzer config: model `{config.get('openrouter_model')}`, "
            f"api_key_configured={config.get('openrouter_api_key_configured')}"
        )
    leaderboard = report.get("leaderboard") or {}
    if leaderboard:
        lines.append(
            f"- Best backend: **{leaderboard.get('best_spec')}** "
            f"(accept pass {leaderboard.get('best_overall_pass_rate')}, "
            f"P@3 {leaderboard.get('best_precision_at_3')})"
        )
    lines.append("")

    header = "| " + " | ".join(label for _, label in _MARKDOWN_COLUMNS) + " |"
    divider = "| " + " | ".join("---" for _ in _MARKDOWN_COLUMNS) + " |"
    lines.append(header)
    lines.append(divider)
    for row in report.get("models", []):
        if row.get("status") == "skipped":
            cells = [
                str(row.get("spec", "")),
                "skipped",
                str(row.get("analyzer_mode", "")),
            ]
            cells += ["-"] * (len(_MARKDOWN_COLUMNS) - len(cells))
            lines.append("| " + " | ".join(cells) + " |")
            continue
        cells = [_format_cell(row.get(key)) for key, _ in _MARKDOWN_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    _append_diagnostics(lines, report)

    skipped = [row for row in report.get("models", []) if row.get("status") == "skipped"]
    if skipped:
        lines.append("## Skipped backends")
        lines.append("")
        for row in skipped:
            lines.append(f"- `{row.get('spec')}`: {row.get('skip_reason')}")
        lines.append("")
    return "\n".join(lines)


def _append_diagnostics(lines: list[str], report: dict[str, Any]) -> None:
    diagnostic_rows = [
        row
        for row in report.get("models", [])
        if row.get("status") != "skipped"
        and (row.get("fallback_notes") or row.get("failure_reasons"))
    ]
    if not diagnostic_rows:
        return
    lines.append("## Failure reasons and fallback notes")
    lines.append("")
    for row in diagnostic_rows:
        lines.append(f"- `{row.get('spec')}` ({row.get('analyzer_mode')})")
        if row.get("status") == "fallback_only":
            lines.append(
                "  - result: all reported quality and retrieval metrics are from the "
                "deterministic fallback, not provider generation."
            )
        for note in row.get("fallback_notes", []):
            lines.append(f"  - fallback: {note}")
        for reason in row.get("failure_reasons", []):
            lines.append(f"  - acceptance gap: {reason}")
    lines.append("")


def _format_cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)
