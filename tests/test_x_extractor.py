from __future__ import annotations

import json
from pathlib import Path

from shelf import orchestrator
from shelf.config import Settings
from shelf.extractors.agent_reach import AgentReachCommandResult, AgentReachDoctorResult
from shelf.extractors.base import ExtractionContext, ExtractorResult
from shelf.extractors.x import XPostExtractor
from shelf.orchestrator import ShelfPipeline


class FakeRunner:
    def __init__(
        self,
        doctor_result: AgentReachDoctorResult,
        command_result: AgentReachCommandResult | None = None,
    ) -> None:
        self.doctor_result = doctor_result
        self.command_result = command_result
        self.commands: list[list[str]] = []

    def doctor(self, channel: str) -> AgentReachDoctorResult:
        assert channel == "twitter"
        return self.doctor_result

    def run(self, argv: list[str]) -> AgentReachCommandResult:
        self.commands.append(argv)
        assert self.command_result is not None
        return self.command_result


class FakePublicMetadataExtractor:
    def extract(self, context: ExtractionContext) -> ExtractorResult:
        return ExtractorResult(
            canonical_url=context.url,
            source_type="x_public",
            selected_strategy="PublicMetadataExtractor",
            extraction_status="metadata_only",
            title="Public X metadata",
            description="Metadata that remains available without Agent-Reach.",
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "evidence",
        sqlite_path=tmp_path / ".shelf" / "shelf.sqlite3",
    )


def test_x_agent_reach_output_maps_to_saved_item_fields(tmp_path: Path) -> None:
    payload = {
        "tweet": {
            "text": "Agent-Reach can read this public X post.",
            "user": {"username": "example"},
            "created_at": "2026-06-01T12:00:00Z",
            "url": "https://x.com/example/status/123",
        }
    }
    runner = FakeRunner(
        AgentReachDoctorResult(
            available=True,
            status="ok",
            active_backend="twitter-cli",
            raw={"twitter": {"status": "ok", "active_backend": "twitter-cli"}},
        ),
        AgentReachCommandResult(
            ok=True,
            argv=["twitter", "tweet", "https://x.com/example/status/123", "--json"],
            stdout=json.dumps(payload),
            returncode=0,
        ),
    )
    extractor = XPostExtractor(_settings(tmp_path), runner=runner)

    result = extractor.extract(
        ExtractionContext(
            item_id="x_1",
            url="https://x.com/example/status/123?s=20",
            raw_dir=tmp_path / "raw",
        )
    )

    assert result.source_type == "x_public"
    assert result.selected_strategy == "XPostExtractor"
    assert result.extraction_status == "success"
    assert result.creator_or_author == "example"
    assert result.canonical_url == "https://x.com/example/status/123"
    assert result.extracted_text == "Agent-Reach can read this public X post."
    assert runner.commands == [
        ["twitter", "tweet", "https://x.com/example/status/123?s=20", "--json"]
    ]
    evidence = tmp_path / "raw" / "x_1" / "x_agent_reach_response.json"
    assert evidence.exists()
    assert "Agent-Reach can read this public X post" in evidence.read_text()


def test_x_agent_reach_unavailable_uses_public_metadata_fallback(tmp_path: Path) -> None:
    runner = FakeRunner(
        AgentReachDoctorResult(
            available=False,
            error_code="agent_reach_not_installed",
            error_message="agent-reach CLI is not installed.",
        )
    )
    extractor = XPostExtractor(
        _settings(tmp_path),
        runner=runner,
        metadata_extractor=FakePublicMetadataExtractor(),  # type: ignore[arg-type]
    )

    result = extractor.extract(
        ExtractionContext(item_id="x_2", url="https://x.com/example/status/456")
    )

    assert result.extraction_status == "metadata_only"
    assert result.title == "Public X metadata"
    assert result.selected_strategy == "XPostExtractor"
    assert result.error_code == "agent_reach_not_installed"
    assert "Public metadata fallback returned metadata_only" in (result.error_message or "")


def test_pipeline_analyzes_x_fallback_record(monkeypatch, tmp_path: Path) -> None:
    class FakeXPostExtractor:
        def extract(self, context: ExtractionContext) -> ExtractorResult:
            return ExtractorResult(
                canonical_url=context.url,
                source_type="x_public",
                selected_strategy="XPostExtractor",
                extraction_status="metadata_only",
                title="Investment thread on X",
                description="A public post about index fund investing.",
                error_code="agent_reach_not_installed",
                error_message="Agent-Reach unavailable; metadata fallback used.",
            )

    monkeypatch.setattr(orchestrator, "XPostExtractor", lambda _settings: FakeXPostExtractor())
    csv_path = tmp_path / "x.csv"
    csv_path.write_text(
        "\n".join(
            [
                "item_id,url,theme_hint,notes",
                "x_item,https://x.com/example/status/789,investment education,fixture",
            ]
        ),
        encoding="utf-8",
    )

    result = ShelfPipeline(_settings(tmp_path)).run_csv(csv_path)

    item = result.items[0]
    assert item.source_type == "x_public"
    assert item.selected_strategy == "XPostExtractor"
    assert item.extraction_status == "metadata_only"
    assert item.summary
    assert item.collection == "Metadata Only"
    assert "fallback" in {event.stage for event in result.traces}
