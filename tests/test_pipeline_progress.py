from pathlib import Path

from shelf.config import Settings
from shelf.orchestrator import ShelfPipeline


def test_pipeline_emits_progress_messages(tmp_path: Path) -> None:
    csv_path = tmp_path / "urls.csv"
    csv_path.write_text(
        "\n".join(
            [
                "item_id,url,theme_hint,notes",
                "bad_url,not-a-url,,Rejected URL avoids network access.",
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "evidence",
        sqlite_path=tmp_path / ".shelf" / "shelf.sqlite3",
    )
    messages: list[str] = []

    ShelfPipeline(settings, progress=messages.append).run_csv(csv_path)

    assert "Progress: [1/1] bad_url: triaging" in messages
    assert any("extracting with UnsupportedExtractor" in message for message in messages)
    assert any("analyzing with DeterministicAnalyzer" in message for message in messages)
    assert any("assigned Needs Review" in message for message in messages)
