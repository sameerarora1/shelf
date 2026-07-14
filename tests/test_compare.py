import json
from types import SimpleNamespace

from shelf.analysis.compare import (
    ComparisonRun,
    ModelComparison,
    build_analyzer,
    compare_analyzer_backends,
    default_model_specs,
    render_markdown_report,
    run_comparison,
)
from shelf.analysis.deterministic import DeterministicAnalyzer
from shelf.analysis.openai_provider import OpenAIAnalyzer
from shelf.cli import _slug, _write_comparison_evidence
from shelf.config import Settings
from shelf.models import SavedItem, TraceEvent

REQUIRED_STAGES = [
    "triage",
    "strategy_selection",
    "extraction",
    "validation",
    "analysis",
    "organization",
    "indexing",
    "persistence",
]


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **kwargs):
        response = self.responses.pop(0)
        content = response if isinstance(response, str) else json.dumps(response)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _settings(tmp_path):
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "evidence",
        sqlite_path=tmp_path / ".shelf" / "shelf.sqlite3",
    )


def _item(item_id, theme, title, text, **overrides):
    data = {
        "item_id": item_id,
        "url": f"https://example.com/{item_id}",
        "canonical_url": f"https://example.com/{item_id}",
        "source_type": "public_webpage",
        "theme_hint": theme,
        "selected_strategy": "WebPageExtractor",
        "extraction_status": "success",
        "title": title,
        "description": title,
        "extracted_text": text,
        "text_available": True,
        "text_character_count": len(text),
        "trace_id": f"trace_{item_id}",
    }
    data.update(overrides)
    return SavedItem(**data)


def _traces_for(item: SavedItem):
    events = []
    for seq, stage in enumerate(REQUIRED_STAGES, start=1):
        events.append(
            TraceEvent(
                trace_id=item.trace_id,
                item_id=item.item_id,
                sequence=seq,
                stage=stage,
                action=stage,
                decision="ok",
                reason="test",
                tool="test",
                status="ok",
            )
        )
    return events


def _llm_payload(topic, category, content_type, intent):
    return {
        "summary": "Short summary.",
        "topics": [topic],
        "entities": [],
        "content_type": content_type,
        "intent_tags": [intent],
        "evidence_notes": ["validated by test"],
        "category_decision": {
            "action": "use_existing",
            "category": category,
            "confidence": 0.9,
            "reason": "Test classification.",
        },
    }


def _write_queries(tmp_path):
    path = tmp_path / "queries.csv"
    path.write_text(
        "query_id,query,relevant_item_ids\n"
        "q1,high protein vegetarian dinner,veg_web_1\n"
        "q2,beginner bodyweight workout,gym_web_1\n",
        encoding="utf-8",
    )
    return path


def test_build_analyzer_resolves_deterministic(tmp_path):
    analyzer = build_analyzer("deterministic", _settings(tmp_path))
    assert isinstance(analyzer, DeterministicAnalyzer)


def test_build_analyzer_resolves_unavailable_without_api_key(monkeypatch, tmp_path):
    # The unavailable backend must not require credentials; it wraps the real
    # OpenAIAnalyzer with a stub client so no network call happens.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    analyzer = build_analyzer("unavailable", _settings(tmp_path))
    assert isinstance(analyzer, OpenAIAnalyzer)
    assert analyzer.mode == "openrouter"


def test_default_model_specs_include_requested_free_models_once(tmp_path):
    settings = _settings(tmp_path)
    specs = default_model_specs(settings)

    assert specs[0] == "deterministic"
    assert "openrouter/free" in specs
    assert "tencent/hy3:free" in specs
    assert "poolside/laguna-m.1:free" in specs
    assert specs[-1] == "unavailable"

    duplicate_default = Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "evidence",
        sqlite_path=tmp_path / ".shelf" / "shelf.sqlite3",
        openrouter_model="tencent/hy3:free",
    )
    assert default_model_specs(duplicate_default).count("tencent/hy3:free") == 1


def test_compare_backends_scores_each_analyzer(tmp_path):
    veg = _item(
        "veg_web_1",
        "vegetarian recipes",
        "High protein vegetarian dinner",
        "A high protein vegetarian tofu and chickpea recipe dinner with beans.",
    )
    gym = _item(
        "gym_web_1",
        "gym exercise",
        "Beginner bodyweight workout",
        "A beginner bodyweight workout with exercise sets and reps for strength.",
    )
    base_items = [veg, gym]
    traces = _traces_for(veg) + _traces_for(gym)
    queries_csv = _write_queries(tmp_path)

    fake_llm = OpenAIAnalyzer(
        model="fake-llm",
        client=FakeClient(
            [
                _llm_payload("vegetarian", "Vegetarian Recipes", "recipe", "cook"),
                _llm_payload("exercise", "Gym and Exercise", "exercise guide", "train"),
            ]
        ),
    )
    backends = [
        ("deterministic", DeterministicAnalyzer()),
        ("fake-llm", fake_llm),
    ]

    rows = compare_analyzer_backends(base_items, traces, backends, queries_csv)

    assert len(rows) == 2
    by_spec = {row.spec: row for row in rows}
    det = by_spec["deterministic"]
    llm = by_spec["fake-llm"]

    assert det.item_count == 2
    assert det.overall_pass_rate == 1.0
    assert det.analysis_modes == {"deterministic": 2}
    assert det.retrieval_status == "evaluated"
    assert det.evaluated_query_count == 2
    # Re-analyzed items are retained for evidence persistence.
    assert len(det.reanalyzed_items) == 2

    assert llm.item_count == 2
    assert llm.analyzer_mode == "openrouter"
    assert llm.analysis_modes == {"openrouter": 2}
    assert llm.fallback_to_deterministic == 0
    assert llm.overall_pass_rate == 1.0
    assert llm.fallback_notes == []


def test_compare_backends_records_llm_fallback(tmp_path):
    veg = _item(
        "veg_web_1",
        "vegetarian recipes",
        "High protein vegetarian dinner",
        "A high protein vegetarian tofu and chickpea recipe dinner with beans.",
    )
    queries_csv = _write_queries(tmp_path)
    # A malformed (non-JSON) response forces the deterministic fallback path.
    fake_llm = OpenAIAnalyzer(model="fake-llm", client=FakeClient(["not json at all"]))
    rows = compare_analyzer_backends([veg], _traces_for(veg), [("fake-llm", fake_llm)], queries_csv)

    assert len(rows) == 1
    row = rows[0]
    assert row.analysis_modes == {"deterministic": 1}
    assert row.fallback_to_deterministic == 1
    assert any("fallback" in note.lower() for note in row.fallback_notes)


def test_unavailable_backend_demonstrates_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    veg = _item(
        "veg_web_1",
        "vegetarian recipes",
        "High protein vegetarian dinner",
        "A high protein vegetarian tofu and chickpea recipe dinner with beans.",
    )
    queries_csv = _write_queries(tmp_path)
    analyzer = build_analyzer("unavailable", _settings(tmp_path))
    rows = compare_analyzer_backends(
        [veg], _traces_for(veg), [("unavailable", analyzer)], queries_csv
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.analyzer_mode == "openrouter"
    assert row.analysis_modes == {"deterministic": 1}
    assert row.fallback_to_deterministic == 1
    assert row.fallback_notes  # fallback reason is surfaced, not silent
    # The fallback still yields a valid deterministic record.
    assert row.reanalyzed_items[0].analysis_mode == "deterministic"


def test_run_comparison_offline_reports_config_and_items(tmp_path):
    # ftp:// URLs route offline to the UnsupportedExtractor (no network),
    # exercising run_comparison end-to-end deterministically.
    input_csv = tmp_path / "urls.csv"
    input_csv.write_text(
        "item_id,url,theme_hint,notes\n"
        "u1,ftp://example.com/one,vegetarian recipes,offline rejected\n"
        "u2,ftp://example.com/two,gym exercise,offline rejected\n",
        encoding="utf-8",
    )
    queries_csv = tmp_path / "queries.csv"
    queries_csv.write_text(
        "query_id,query,relevant_item_ids\nq1,offline record,u1\n",
        encoding="utf-8",
    )

    run = run_comparison(
        _settings(tmp_path),
        input_csv,
        queries_csv,
        ["deterministic", "unavailable"],
        raw_dir=tmp_path / "raw",
    )

    assert run.report["item_count"] == 2
    assert "config" in run.report
    assert run.report["config"]["analyzer"] == "deterministic"
    # The redacted config never carries the secret itself, only a boolean.
    assert "openrouter_api_key_configured" in run.report["config"]
    assert set(run.report["config"]).isdisjoint({"OPENROUTER_API_KEY", "api_key"})

    evaluated = [row for row in run.rows if row.status == "evaluated"]
    assert len(evaluated) == 2
    assert all(len(row.reanalyzed_items) == 2 for row in evaluated)


def test_write_comparison_evidence_persists_sanitized_files(tmp_path):
    item = _item(
        "veg_web_1",
        "vegetarian recipes",
        "High protein vegetarian dinner",
        "A vegetarian tofu recipe.",
    )
    row = ModelComparison(
        spec="nvidia/nemotron-3-ultra-550b-a55b:free",
        analyzer_mode="openrouter",
        item_count=1,
        reanalyzed_items=[item],
    )
    skipped = ModelComparison(
        spec="some/other-model",
        analyzer_mode="openrouter",
        status="skipped",
        skip_reason="OPENROUTER_API_KEY is required.",
    )
    report = {
        "config": {"analyzer": "openrouter", "openrouter_api_key_configured": True},
        "models": [row.to_dict(), skipped.to_dict()],
    }
    run = ComparisonRun(report=report, rows=[row, skipped], base_traces=_traces_for(item))

    out = tmp_path / "compare"
    _write_comparison_evidence(out, run)

    assert (out / "comparison.json").exists()
    assert (out / "comparison.md").exists()
    assert (out / "config.json").exists()
    assert (out / "traces.jsonl").exists()
    backend_items = out / _slug(row.spec) / "items.jsonl"
    assert backend_items.exists()
    # Skipped backend must not persist re-analyzed items.
    assert not (out / _slug(skipped.spec)).exists()
    # No secret is ever written into evidence.
    written = (out / "config.json").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY" not in written


def test_render_markdown_report_includes_rows_config_and_diagnostics():
    fallback_row = ModelComparison(
        spec="unavailable",
        analyzer_mode="openrouter",
        item_count=10,
        analysis_modes={"deterministic": 10},
        fallback_to_deterministic=10,
        fallback_notes=["OpenRouter analyzer failed; deterministic fallback used: RuntimeError"],
    )
    report = {
        "generated_at": "2026-07-11T00:00:00+00:00",
        "dataset": "data/urls.csv",
        "queries": "data/retrieval_queries.csv",
        "item_count": 10,
        "trace_count": 83,
        "config": {
            "openrouter_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "openrouter_api_key_configured": False,
        },
        "leaderboard": {
            "best_spec": "deterministic",
            "best_overall_pass_rate": 1.0,
            "best_precision_at_3": 0.66,
            "best_mrr": 1.0,
        },
        "models": [
            ModelComparison(spec="deterministic", analyzer_mode="deterministic").to_dict(),
            fallback_row.to_dict(),
            {
                "spec": "some/model",
                "analyzer_mode": "openrouter",
                "status": "skipped",
                "skip_reason": "OPENROUTER_API_KEY is required.",
            },
        ],
    }
    markdown = render_markdown_report(report)
    assert "Analyzer Comparison Across Backends" in markdown
    assert "deterministic" in markdown
    assert "skipped" in markdown
    assert "OPENROUTER_API_KEY is required." in markdown
    assert "api_key_configured=False" in markdown
    assert "Failure reasons and fallback notes" in markdown
    assert "deterministic fallback used" in markdown
