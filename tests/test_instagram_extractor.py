from __future__ import annotations

import json
from pathlib import Path

from shelf import orchestrator
from shelf.config import Settings
from shelf.extractors.agent_reach import AgentReachCommandResult, AgentReachDoctorResult
from shelf.extractors.base import ExtractionContext, ExtractorResult
from shelf.extractors.instagram import InstagramPostExtractor
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
        assert channel == "instagram"
        return self.doctor_result

    def run(self, argv: list[str]) -> AgentReachCommandResult:
        self.commands.append(argv)
        assert self.command_result is not None
        return self.command_result


class FakePublicMetadataExtractor:
    def extract(self, context: ExtractionContext) -> ExtractorResult:
        return ExtractorResult(
            canonical_url=context.url,
            source_type="instagram_public",
            selected_strategy="PublicMetadataExtractor",
            extraction_status="metadata_only",
            title="Public Instagram metadata",
            description="Metadata that remains available without Agent-Reach.",
        )


def _settings(tmp_path: Path, *, command: str = "") -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        evidence_dir=tmp_path / "evidence",
        sqlite_path=tmp_path / ".shelf" / "shelf.sqlite3",
        agent_reach_instagram_command=command,
    )


def test_instagram_agent_reach_output_maps_to_saved_item_fields(tmp_path: Path) -> None:
    payload = {
        "post": {
            "caption": "A public Instagram post caption.",
            "user": {"username": "example"},
            "taken_at": "2026-06-01T12:00:00Z",
            "url": "https://www.instagram.com/p/ABC123/",
            "media_type": "carousel",
        }
    }
    runner = FakeRunner(
        AgentReachDoctorResult(
            available=True,
            status="ok",
            active_backend="OpenCLI",
            raw={"instagram": {"status": "ok", "active_backend": "OpenCLI"}},
        ),
        AgentReachCommandResult(
            ok=True,
            argv=["opencli", "instagram", "post", "https://www.instagram.com/p/ABC123/"],
            stdout=json.dumps(payload),
            returncode=0,
        ),
    )
    extractor = InstagramPostExtractor(
        _settings(tmp_path, command="opencli instagram post {url} -f json"),
        runner=runner,
    )

    result = extractor.extract(
        ExtractionContext(
            item_id="ig_1",
            url="https://www.instagram.com/p/ABC123/?img_index=1",
            raw_dir=tmp_path / "raw",
        )
    )

    assert result.source_type == "instagram_public"
    assert result.selected_strategy == "InstagramPostExtractor"
    assert result.extraction_status == "success"
    assert result.creator_or_author == "example"
    assert result.canonical_url == "https://www.instagram.com/p/ABC123/"
    assert result.extracted_text == "A public Instagram post caption."
    assert runner.commands == [
        [
            "opencli",
            "instagram",
            "post",
            "https://www.instagram.com/p/ABC123/?img_index=1",
            "-f",
            "json",
        ]
    ]
    evidence = tmp_path / "raw" / "ig_1" / "instagram_agent_reach_response.json"
    assert evidence.exists()
    assert "A public Instagram post caption" in evidence.read_text()


def test_instagram_missing_post_command_uses_public_metadata_fallback(tmp_path: Path) -> None:
    runner = FakeRunner(
        AgentReachDoctorResult(
            available=True,
            status="ok",
            active_backend="OpenCLI",
            raw={"instagram": {"status": "ok", "active_backend": "OpenCLI"}},
        )
    )
    extractor = InstagramPostExtractor(
        _settings(tmp_path),
        runner=runner,
        metadata_extractor=FakePublicMetadataExtractor(),  # type: ignore[arg-type]
    )

    result = extractor.extract(
        ExtractionContext(item_id="ig_2", url="https://www.instagram.com/p/DEF456/")
    )

    assert result.extraction_status == "metadata_only"
    assert result.title == "Public Instagram metadata"
    assert result.selected_strategy == "InstagramPostExtractor"
    assert result.error_code == "agent_reach_instagram_post_command_missing"
    assert "direct /p/" in (result.error_message or "")


def test_pipeline_analyzes_instagram_fallback_record(monkeypatch, tmp_path: Path) -> None:
    class FakeInstagramPostExtractor:
        def extract(self, context: ExtractionContext) -> ExtractorResult:
            return ExtractorResult(
                canonical_url=context.url,
                source_type="instagram_public",
                selected_strategy="InstagramPostExtractor",
                extraction_status="metadata_only",
                title="Fitness post on Instagram",
                description="A public post about bodyweight exercise.",
                error_code="agent_reach_instagram_post_command_missing",
                error_message="Agent-Reach Instagram direct post command is not configured.",
            )

    monkeypatch.setattr(
        orchestrator,
        "InstagramPostExtractor",
        lambda _settings: FakeInstagramPostExtractor(),
    )
    csv_path = tmp_path / "instagram.csv"
    csv_path.write_text(
        "\n".join(
            [
                "item_id,url,theme_hint,notes",
                "ig_item,https://www.instagram.com/p/XYZ123/,gym exercise,fixture",
            ]
        ),
        encoding="utf-8",
    )

    result = ShelfPipeline(_settings(tmp_path)).run_csv(csv_path)

    item = result.items[0]
    assert item.source_type == "instagram_public"
    assert item.selected_strategy == "InstagramPostExtractor"
    assert item.extraction_status == "metadata_only"
    assert item.summary
    assert item.collection == "Metadata Only"
    assert "fallback" in {event.stage for event in result.traces}
