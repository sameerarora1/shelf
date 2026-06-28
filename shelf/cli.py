from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Annotated

import typer

from shelf.analysis.deterministic import DeterministicAnalyzer
from shelf.analysis.evaluate import evaluate_analysis_quality
from shelf.analysis.openai_provider import OpenAIAnalyzer
from shelf.config import Settings, ensure_project_dirs
from shelf.orchestrator import ShelfPipeline
from shelf.organization.organizer import Organizer, group_collections
from shelf.retrieval.evaluate import evaluate_queries
from shelf.retrieval.index import TfidfSearchIndex
from shelf.storage.sqlite_store import SQLiteStore

app = typer.Typer(help="Shelf backend validation CLI.")


@app.command()
def init() -> None:
    """Create local data, evidence, and SQLite directories."""
    settings = Settings.from_env()
    ensure_project_dirs(settings)
    _write_seed_files(settings, overwrite=False)
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    typer.echo(f"Initialized Shelf project at {settings.project_root}")
    typer.echo(f"SQLite path: {settings.sqlite_path}")


@app.command()
def ingest(
    input_file: Annotated[
        Path,
        typer.Argument(help="CSV with item_id,url,theme_hint,notes"),
    ],
) -> None:
    """Ingest URLs, write evidence, and persist normalized records."""
    settings = Settings.from_env()
    ensure_project_dirs(settings)
    run_dir = settings.evidence_dir / "ingest-latest"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    pipeline = ShelfPipeline(
        settings,
        analyzer=_analyzer(settings),
        organizer=Organizer(),
        progress=typer.echo,
    )
    result = pipeline.run_csv(input_file, raw_dir=run_dir / "raw")
    store = SQLiteStore(settings.sqlite_path)
    store.clear()
    store.upsert_items(result.items)
    store.insert_traces(result.traces)
    _write_evidence(settings.evidence_dir, result.items, result.traces)
    typer.echo(f"Ingested {len(result.items)} items")
    typer.echo(f"Raw evidence: {run_dir / 'raw'}")


@app.command()
def organize() -> None:
    """Re-run collection assignment for persisted items."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    items = store.list_items()
    organizer = Organizer()
    for item in items:
        item.collection = organizer.assign(item).collection
    store.upsert_items(items)
    collections = group_collections(items)
    typer.echo(json.dumps(collections, indent=2, sort_keys=True))


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    top_k: Annotated[int, typer.Option("--top-k", min=1, max=20)] = 3,
) -> None:
    """Search persisted items with the TF-IDF baseline."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    items = store.list_items()
    results = TfidfSearchIndex(items).search(query, top_k=top_k)
    typer.echo(json.dumps([result.__dict__ for result in results], indent=2, sort_keys=True))


@app.command()
def evaluate(
    queries_csv: Annotated[Path, typer.Argument(help="CSV with query_id,query,relevant_item_ids")]
) -> None:
    """Evaluate persisted items against labeled retrieval queries."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    metrics, details = evaluate_queries(store.list_items(), queries_csv)
    typer.echo(json.dumps({"metrics": metrics, "results": details}, indent=2, sort_keys=True))


@app.command("evaluate-analysis")
def evaluate_analysis() -> None:
    """Evaluate analyzer output quality and trace coverage for persisted items."""
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    metrics, details = evaluate_analysis_quality(store.list_items(), store.list_traces())
    typer.echo(json.dumps({"metrics": metrics, "results": details}, indent=2, sort_keys=True))


def _analyzer(settings: Settings):
    if settings.analyzer in {"openrouter", "openai"}:
        return OpenAIAnalyzer(
            settings.openrouter_model,
            base_url=settings.openrouter_base_url,
            timeout_seconds=settings.openrouter_timeout_seconds,
        )
    return DeterministicAnalyzer()


def _write_evidence(evidence_dir: Path, items, traces) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    items_jsonl = "\n".join(item.model_dump_json() for item in items) + "\n"
    traces_jsonl = "\n".join(trace.model_dump_json() for trace in traces) + "\n"
    (evidence_dir / "items.jsonl").write_text(items_jsonl, encoding="utf-8")
    (evidence_dir / "traces.jsonl").write_text(traces_jsonl, encoding="utf-8")
    (evidence_dir / "output.json").write_text(
        json.dumps(
            {
                "items": [item.model_dump(mode="json") for item in items],
                "collections": group_collections(items),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_seed_files(settings: Settings, *, overwrite: bool) -> None:
    urls = settings.data_dir / "urls.csv"
    queries = settings.data_dir / "retrieval_queries.csv"
    for path, rows in [(urls, SEED_URL_ROWS)]:
        if overwrite or not path.exists():
            _write_csv(path, ["item_id", "url", "theme_hint", "notes"], rows)
    for path, rows in [(queries, SEED_QUERY_ROWS)]:
        if overwrite or not path.exists():
            _write_csv(path, ["query_id", "query", "relevant_item_ids"], rows)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


SEED_URL_ROWS = [
    {
        "item_id": "veg_web_1",
        "url": "https://ohmyveggies.com/vegetable-and-chickpea-sheet-pan-meal/",
        "theme_hint": "vegetarian recipes",
        "notes": "Vegetable and chickpea sheet-pan recipe.",
    },
    {
        "item_id": "veg_web_2",
        "url": "https://www.budgetbytes.com/category/recipes/vegetarian/",
        "theme_hint": "vegetarian recipes",
        "notes": "Public vegetarian recipe index.",
    },
    {
        "item_id": "invest_web_1",
        "url": "https://www.bogleheads.org/wiki/Getting_started",
        "theme_hint": "investment education",
        "notes": "Public investing education wiki page.",
    },
    {
        "item_id": "invest_web_2",
        "url": "https://www.bogleheads.org/wiki/Index_fund",
        "theme_hint": "investment education",
        "notes": "Public index fund explainer.",
    },
    {
        "item_id": "gym_web_1",
        "url": "https://en.wikipedia.org/wiki/Bodyweight_exercise",
        "theme_hint": "gym exercise",
        "notes": "Public bodyweight exercise reference page.",
    },
    {
        "item_id": "veg_yt_1",
        "url": "https://www.youtube.com/watch?v=Sf0miHIujeI",
        "theme_hint": "vegetarian recipes",
        "notes": "Public YouTube high-protein vegetarian dinner result.",
    },
    {
        "item_id": "invest_yt_1",
        "url": "https://www.youtube.com/watch?v=fYYPRtRZ9Gg",
        "theme_hint": "investment education",
        "notes": "Public YouTube index funds versus ETF education result.",
    },
    {
        "item_id": "gym_yt_1",
        "url": "https://www.youtube.com/watch?v=dcKwz_C8pkg",
        "theme_hint": "gym exercise",
        "notes": "Public YouTube beginner bodyweight workout result.",
    },
    {
        "item_id": "veg_yt_2",
        "url": "https://www.youtube.com/watch?v=dfI7nJFXaFA",
        "theme_hint": "vegetarian recipes",
        "notes": "Public YouTube high-protein vegan meals result.",
    },
    {
        "item_id": "social_x_1",
        "url": "https://x.com/sensa_market/status/2067592665777238255",
        "theme_hint": "investment education",
        "notes": "Expected metadata-only or blocked fallback; no login or cookies used.",
    },
]


SEED_QUERY_ROWS = [
    {
        "query_id": "q1",
        "query": "high protein vegetarian dinner",
        "relevant_item_ids": "veg_web_1|veg_web_2|veg_yt_1|veg_yt_2",
    },
    {
        "query_id": "q2",
        "query": "index funds beginner investing",
        "relevant_item_ids": "invest_web_1|invest_web_2|invest_yt_1",
    },
    {
        "query_id": "q3",
        "query": "beginner bodyweight workout",
        "relevant_item_ids": "gym_web_1|gym_yt_1",
    },
]


if __name__ == "__main__":
    app()
