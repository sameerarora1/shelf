from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared but optional at import time
    load_dotenv = None


DEFAULT_USER_AGENT = "ShelfCheckpoint1/0.1 (+https://github.com/infinityaurora6/shelf)"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_OPENROUTER_TIMEOUT_SECONDS = 30.0
DEFAULT_AGENT_REACH_X_COMMAND = "twitter tweet {url} --json"


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    evidence_dir: Path
    sqlite_path: Path
    analyzer: str = "deterministic"
    openrouter_base_url: str = DEFAULT_OPENROUTER_BASE_URL
    openrouter_model: str = DEFAULT_OPENROUTER_MODEL
    openrouter_timeout_seconds: float = DEFAULT_OPENROUTER_TIMEOUT_SECONDS
    http_timeout_seconds: float = 15.0
    http_max_redirects: int = 5
    http_max_bytes: int = 2_000_000
    raw_html_max_chars: int = 120_000
    user_agent: str = DEFAULT_USER_AGENT
    agent_reach_timeout_seconds: float = 30.0
    agent_reach_x_command: str = DEFAULT_AGENT_REACH_X_COMMAND

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or Path.cwd()).resolve()
        if load_dotenv is not None:
            load_dotenv(root / ".env")
        return cls(
            project_root=root,
            data_dir=root / "data",
            evidence_dir=root / "evidence",
            sqlite_path=root / ".shelf" / "shelf.sqlite3",
            analyzer=os.getenv("SHELF_ANALYZER", "deterministic").strip().lower()
            or "deterministic",
            openrouter_base_url=os.getenv(
                "OPENROUTER_BASE_URL",
                DEFAULT_OPENROUTER_BASE_URL,
            ).strip()
            or DEFAULT_OPENROUTER_BASE_URL,
            openrouter_model=os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip()
            or DEFAULT_OPENROUTER_MODEL,
            openrouter_timeout_seconds=float(
                os.getenv("OPENROUTER_TIMEOUT_SECONDS", str(DEFAULT_OPENROUTER_TIMEOUT_SECONDS))
            ),
            http_timeout_seconds=float(os.getenv("SHELF_HTTP_TIMEOUT_SECONDS", "15")),
            http_max_redirects=int(os.getenv("SHELF_HTTP_MAX_REDIRECTS", "5")),
            http_max_bytes=int(os.getenv("SHELF_HTTP_MAX_BYTES", "2000000")),
            raw_html_max_chars=int(os.getenv("SHELF_RAW_HTML_MAX_CHARS", "120000")),
            user_agent=os.getenv("SHELF_USER_AGENT", DEFAULT_USER_AGENT).strip()
            or DEFAULT_USER_AGENT,
            agent_reach_timeout_seconds=float(
                os.getenv("SHELF_AGENT_REACH_TIMEOUT_SECONDS", "30")
            ),
            agent_reach_x_command=os.getenv(
                "SHELF_AGENT_REACH_X_COMMAND",
                DEFAULT_AGENT_REACH_X_COMMAND,
            ).strip()
            or DEFAULT_AGENT_REACH_X_COMMAND,
        )

    def redacted_config(self) -> dict[str, str | int | float]:
        return {
            "analyzer": self.analyzer,
            "openrouter_model": self.openrouter_model,
            "openrouter_base_url": self.openrouter_base_url,
            "openrouter_timeout_seconds": self.openrouter_timeout_seconds,
            "openrouter_api_key_configured": bool(os.getenv("OPENROUTER_API_KEY")),
            "http_timeout_seconds": self.http_timeout_seconds,
            "http_max_redirects": self.http_max_redirects,
            "http_max_bytes": self.http_max_bytes,
            "raw_html_max_chars": self.raw_html_max_chars,
            "user_agent": self.user_agent,
            "agent_reach_timeout_seconds": self.agent_reach_timeout_seconds,
            "agent_reach_x_command_configured": bool(self.agent_reach_x_command),
            "sqlite_path": str(self.sqlite_path),
        }


def ensure_project_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
