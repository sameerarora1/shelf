from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from shelf.extractors.base import sanitize_error

SENSITIVE_KEY_PATTERN = re.compile(
    r"(auth|cookie|ct0|password|secret|session|token)", flags=re.IGNORECASE
)


@dataclass(frozen=True)
class AgentReachDoctorResult:
    available: bool
    status: str | None = None
    active_backend: str | None = None
    raw: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class AgentReachCommandResult:
    ok: bool
    argv: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    error_code: str | None = None
    error_message: str | None = None


class AgentReachCommandRunner:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def doctor(self, channel: str) -> AgentReachDoctorResult:
        binary = shutil.which("agent-reach")
        if binary is None:
            return AgentReachDoctorResult(
                available=False,
                error_code="agent_reach_not_installed",
                error_message=(
                    "agent-reach CLI is not installed; install the optional "
                    "agent-reach extra to enable this extractor."
                ),
            )
        try:
            completed = subprocess.run(
                [binary, "doctor", "--json"],
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return AgentReachDoctorResult(
                available=False,
                error_code="agent_reach_doctor_timeout",
                error_message=sanitize_error(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return AgentReachDoctorResult(
                available=False,
                error_code="agent_reach_doctor_failed",
                error_message=sanitize_error(exc),
            )

        if completed.returncode != 0:
            return AgentReachDoctorResult(
                available=False,
                error_code="agent_reach_doctor_failed",
                error_message=sanitize_agent_reach_text(completed.stderr or completed.stdout),
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return AgentReachDoctorResult(
                available=False,
                error_code="agent_reach_doctor_invalid_json",
                error_message="agent-reach doctor did not return valid JSON.",
            )

        channel_payload = _channel_payload(payload, channel)
        status = _string_field(channel_payload, "status")
        backend = _string_field(channel_payload, "active_backend") or _string_field(
            channel_payload,
            "backend",
        )
        if status != "ok":
            return AgentReachDoctorResult(
                available=False,
                status=status,
                active_backend=backend,
                raw=sanitize_agent_reach_payload(payload),
                error_code="agent_reach_channel_unavailable",
                error_message=_string_field(channel_payload, "message")
                or f"agent-reach channel {channel!r} is not ready.",
            )
        return AgentReachDoctorResult(
            available=True,
            status=status,
            active_backend=backend,
            raw=sanitize_agent_reach_payload(payload),
        )

    def run(self, argv: list[str]) -> AgentReachCommandResult:
        executable = shutil.which(argv[0])
        if executable is None:
            return AgentReachCommandResult(
                ok=False,
                argv=argv,
                error_code="agent_reach_backend_missing",
                error_message=f"Required Agent-Reach backend command is not installed: {argv[0]}",
            )
        try:
            completed = subprocess.run(
                [executable, *argv[1:]],
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return AgentReachCommandResult(
                ok=False,
                argv=argv,
                error_code="agent_reach_backend_timeout",
                error_message=sanitize_error(exc),
            )
        except Exception as exc:  # noqa: BLE001
            return AgentReachCommandResult(
                ok=False,
                argv=argv,
                error_code="agent_reach_backend_failed",
                error_message=sanitize_error(exc),
            )
        return AgentReachCommandResult(
            ok=completed.returncode == 0,
            argv=argv,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            error_code=None if completed.returncode == 0 else "agent_reach_backend_failed",
            error_message=None
            if completed.returncode == 0
            else sanitize_agent_reach_text(completed.stderr or completed.stdout),
        )


def command_from_template(template: str, **values: str) -> list[str]:
    formatted = template.format(**values)
    return shlex.split(formatted)


def parse_structured_output(output: str) -> Any:
    stripped = output.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        import yaml
    except ImportError:
        return None
    try:
        return yaml.safe_load(stripped)
    except yaml.YAMLError:
        return None


def sanitize_agent_reach_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized = {}
        for key, value in payload.items():
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = sanitize_agent_reach_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_agent_reach_payload(value) for value in payload]
    if isinstance(payload, str):
        return sanitize_agent_reach_text(payload)
    return payload


def sanitize_agent_reach_text(text: str) -> str:
    redacted = re.sub(
        r"(?i)(auth[_-]?token|ct0|cookie|token|password|secret)=([^&\s;]+)",
        r"\1=<redacted>",
        text,
    )
    redacted = re.sub(
        r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._\-]+",
        r"\1<redacted>",
        redacted,
    )
    return redacted[:4000]


def _channel_payload(payload: Any, channel: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    direct = payload.get(channel)
    if isinstance(direct, dict):
        return direct
    channels = payload.get("channels")
    if isinstance(channels, dict) and isinstance(channels.get(channel), dict):
        return channels[channel]
    results = payload.get("results")
    if isinstance(results, dict) and isinstance(results.get(channel), dict):
        return results[channel]
    return {}


def _string_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        return value
    return None
