from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from shelf.config import DEFAULT_AGENT_REACH_X_COMMAND, Settings
from shelf.extractors.agent_reach import (
    AgentReachCommandResult,
    AgentReachCommandRunner,
    AgentReachDoctorResult,
    command_from_template,
    parse_structured_output,
    sanitize_agent_reach_payload,
    sanitize_agent_reach_text,
)
from shelf.extractors.base import (
    ExtractionContext,
    ExtractorResult,
    content_hash,
    write_json,
    write_text,
)
from shelf.extractors.public_metadata import PublicMetadataExtractor
from shelf.trace import Timer


class XPostExtractor:
    selected_strategy = "XPostExtractor"

    def __init__(
        self,
        settings: Settings,
        *,
        runner: AgentReachCommandRunner | None = None,
        metadata_extractor: PublicMetadataExtractor | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or AgentReachCommandRunner(settings.agent_reach_timeout_seconds)
        self.metadata_extractor = metadata_extractor or PublicMetadataExtractor(
            settings,
            "x_public",
        )

    def extract(self, context: ExtractionContext) -> ExtractorResult:
        raw_item_dir = context.raw_dir / context.item_id if context.raw_dir else None
        with Timer() as timer:
            doctor = self.runner.doctor("twitter")
            command_is_overridden = self.settings.agent_reach_x_command != (
                DEFAULT_AGENT_REACH_X_COMMAND
            )
            if doctor.available and (
                command_is_overridden or _supports_direct_x_post_read(doctor.active_backend)
            ):
                command = command_from_template(
                    self.settings.agent_reach_x_command,
                    url=context.url,
                    post_id=_post_id(context.url) or "",
                )
                command_result = self.runner.run(command)
                parsed = parse_structured_output(command_result.stdout)
                if command_result.ok:
                    result = self.map_agent_reach_output_to_result(
                        context.url,
                        parsed,
                        raw_stdout=command_result.stdout,
                        backend=doctor.active_backend,
                    )
                    result.latency_ms = timer.elapsed_ms
                    if raw_item_dir:
                        _write_success_evidence(
                            raw_item_dir,
                            doctor,
                            command_result,
                            parsed,
                        )
                    return result
                if raw_item_dir:
                    _write_failure_evidence(raw_item_dir, doctor, command_result)
                failure_code = command_result.error_code or "agent_reach_x_failed"
                failure_message = command_result.error_message or "Agent-Reach X command failed."
            elif doctor.available:
                failure_code = "agent_reach_x_backend_unsupported"
                failure_message = (
                    "Agent-Reach reported an active X backend, but this Shelf extractor only "
                    "has a documented direct post command for twitter-cli. Configure "
                    "SHELF_AGENT_REACH_X_COMMAND to opt into another backend."
                )
                if raw_item_dir:
                    _write_failure_evidence(raw_item_dir, doctor, None, failure_message)
            else:
                failure_code = doctor.error_code or "agent_reach_x_unavailable"
                failure_message = doctor.error_message or "Agent-Reach X channel is unavailable."
                if raw_item_dir:
                    _write_failure_evidence(raw_item_dir, doctor, None, failure_message)

            fallback = self.metadata_extractor.extract(context)
            fallback.selected_strategy = self.selected_strategy
            fallback.source_type = "x_public"
            fallback.latency_ms = timer.elapsed_ms
            fallback.error_code = fallback.error_code or failure_code
            fallback.error_message = _combine_failure_messages(failure_message, fallback)
            fallback.metadata["agent_reach_fallback_reason"] = failure_message
            fallback.metadata["agent_reach_error_code"] = failure_code
            return fallback

    def map_agent_reach_output_to_result(
        self,
        url: str,
        payload: Any,
        *,
        raw_stdout: str = "",
        backend: str | None = None,
    ) -> ExtractorResult:
        record = _primary_record(payload)
        text = _first_string(
            record,
            "text",
            "full_text",
            "content",
            "body",
            "tweet",
            "tweet_text",
        )
        if text is None and raw_stdout.strip():
            text = sanitize_agent_reach_text(raw_stdout).strip()
        text = re.sub(r"\s+", " ", text or "").strip() or None
        author = _author(record)
        published = _first_string(record, "created_at", "published_at", "date", "timestamp")
        canonical_url = _first_string(record, "url", "permalink", "link") or _canonical_x_url(url)
        title = _title(record, author, text)
        description = _first_string(record, "description", "summary") or text
        status = "success" if text else "metadata_only"
        return ExtractorResult(
            canonical_url=canonical_url,
            source_type="x_public",
            selected_strategy=self.selected_strategy,
            extraction_status=status,
            title=title,
            creator_or_author=author,
            published_at=published,
            description=description,
            extracted_text=text,
            text_available=bool(text),
            content_hash=content_hash(text or description or title),
            error_code=None if text or title or description else "agent_reach_x_empty",
            error_message=None
            if text or title or description
            else "Agent-Reach returned no usable X post fields.",
            metadata={
                "platform": "x",
                "agent_reach_backend": backend,
                "post_id": _post_id(url),
                "payload_keys": sorted(record.keys()),
            },
        )


def _supports_direct_x_post_read(active_backend: str | None) -> bool:
    return bool(active_backend and "twitter-cli" in active_backend.lower())


def _write_success_evidence(
    raw_item_dir,
    doctor: AgentReachDoctorResult,
    command_result: AgentReachCommandResult,
    parsed: Any,
) -> None:
    write_json(
        raw_item_dir / "x_agent_reach_response.json",
        {
            "doctor": doctor.raw,
            "active_backend": doctor.active_backend,
            "command": command_result.argv,
            "returncode": command_result.returncode,
            "parsed": sanitize_agent_reach_payload(parsed),
        },
    )
    if command_result.stdout:
        write_text(
            raw_item_dir / "x_agent_reach_stdout_limited.txt",
            sanitize_agent_reach_text(command_result.stdout),
        )


def _write_failure_evidence(
    raw_item_dir,
    doctor: AgentReachDoctorResult,
    command_result: AgentReachCommandResult | None = None,
    message: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "doctor": doctor.raw,
        "active_backend": doctor.active_backend,
        "doctor_error_code": doctor.error_code,
        "doctor_error_message": doctor.error_message,
        "message": message,
    }
    if command_result is not None:
        payload.update(
            {
                "command": command_result.argv,
                "returncode": command_result.returncode,
                "stdout": sanitize_agent_reach_text(command_result.stdout),
                "stderr": sanitize_agent_reach_text(command_result.stderr),
                "command_error_code": command_result.error_code,
                "command_error_message": command_result.error_message,
            }
        )
    write_json(raw_item_dir / "x_agent_reach_error.json", sanitize_agent_reach_payload(payload))


def _combine_failure_messages(agent_reach_message: str, fallback: ExtractorResult) -> str:
    if fallback.error_message:
        return f"{agent_reach_message} Public metadata fallback: {fallback.error_message}"
    return f"{agent_reach_message} Public metadata fallback returned {fallback.extraction_status}."


def _primary_record(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        for key in ("tweet", "post", "data", "result"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        return payload
    if isinstance(payload, list):
        first = next((item for item in payload if isinstance(item, dict)), None)
        return first or {}
    return {}


def _first_string(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int | float):
            return str(value)
    return None


def _author(record: dict[str, Any]) -> str | None:
    user = record.get("user") or record.get("author")
    if isinstance(user, dict):
        return _first_string(user, "username", "screen_name", "name", "display_name")
    if isinstance(user, str) and user.strip():
        return user.strip()
    return _first_string(record, "username", "screen_name", "author_name", "display_name")


def _title(record: dict[str, Any], author: str | None, text: str | None) -> str | None:
    explicit = _first_string(record, "title")
    if explicit:
        return explicit
    if not text:
        return None
    prefix = f"{author}: " if author else "X post: "
    title = prefix + text
    return title[:117].rstrip() + "..." if len(title) > 120 else title


def _post_id(url: str) -> str | None:
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else None


def _canonical_x_url(url: str) -> str:
    parsed = urlparse(url)
    post_id = _post_id(url)
    if not post_id:
        return url
    parts = [part for part in parsed.path.split("/") if part]
    username = parts[0] if parts else "i"
    return f"https://x.com/{username}/status/{post_id}"
