from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from shelf.models import SavedItem, TraceEvent


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_items (
                    item_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    extraction_status TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    item_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_events (
                    trace_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY (trace_id, sequence)
                )
                """
            )

    def clear(self) -> None:
        self.init_db()
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM trace_events")
            conn.execute("DELETE FROM saved_items")

    def upsert_items(self, items: list[SavedItem]) -> None:
        self.init_db()
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """
                INSERT INTO saved_items (
                    item_id, url, title, extraction_status, collection, item_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    url=excluded.url,
                    title=excluded.title,
                    extraction_status=excluded.extraction_status,
                    collection=excluded.collection,
                    item_json=excluded.item_json
                """,
                [
                    (
                        item.item_id,
                        str(item.url),
                        item.title,
                        item.extraction_status,
                        item.collection,
                        item.model_dump_json(),
                    )
                    for item in items
                ],
            )

    def insert_traces(self, traces: list[TraceEvent]) -> None:
        self.init_db()
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO trace_events (trace_id, item_id, sequence, event_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        trace.trace_id,
                        trace.item_id,
                        trace.sequence,
                        trace.model_dump_json(),
                    )
                    for trace in traces
                ],
            )

    def list_items(self) -> list[SavedItem]:
        self.init_db()
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT item_json FROM saved_items ORDER BY item_id").fetchall()
        return [SavedItem.model_validate_json(row[0]) for row in rows]

    def list_traces(self) -> list[TraceEvent]:
        self.init_db()
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT event_json FROM trace_events ORDER BY trace_id, sequence"
            ).fetchall()
        return [TraceEvent.model_validate_json(row[0]) for row in rows]

    def write_debug_dump(self, path: Path) -> None:
        payload = {
            "items": [json.loads(item.model_dump_json()) for item in self.list_items()],
            "traces": [json.loads(trace.model_dump_json()) for trace in self.list_traces()],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
