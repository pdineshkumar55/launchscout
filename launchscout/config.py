"""Settings loaded from .env. Every limit can be overridden there."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Keep framework telemetry off even if .env forgets it.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _key(name: str) -> str:
    value = os.getenv(name, "").strip()
    return "" if value.startswith("your-") else value


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = field(repr=False, default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    # Search: SerpApi first (has review excerpts), Serper.dev as fallback when SerpApi runs out.
    serpapi_api_key: str = field(repr=False, default_factory=lambda: _key("SERPAPI_API_KEY"))
    serper_api_key: str = field(repr=False, default_factory=lambda: _key("SERPER_API_KEY"))

    model_default: str = field(default_factory=lambda: os.getenv("MODEL_DEFAULT", "gpt-4o-mini"))
    model_strategy: str = field(default_factory=lambda: os.getenv("MODEL_STRATEGY", "gpt-4o-mini"))

    access_code: str = field(repr=False, default_factory=lambda: os.getenv("ACCESS_CODE", ""))

    max_runs_per_session: int = field(default_factory=lambda: _int("MAX_RUNS_PER_SESSION", 3))
    daily_run_cap: int = field(default_factory=lambda: _int("DAILY_RUN_CAP", 20))
    max_concurrent_runs: int = field(default_factory=lambda: _int("MAX_CONCURRENT_RUNS", 2))
    max_searches_per_run: int = field(default_factory=lambda: _int("MAX_SEARCHES_PER_RUN", 15))
    max_page_fetches_per_run: int = field(default_factory=lambda: _int("MAX_PAGE_FETCHES_PER_RUN", 15))
    max_llm_calls_per_run: int = field(default_factory=lambda: _int("MAX_LLM_CALLS_PER_RUN", 60))
    run_timeout_seconds: int = field(default_factory=lambda: _int("RUN_TIMEOUT_SECONDS", 480))

    # Agent limits
    agent_max_iter: int = 8
    agent_max_rpm: int = 20
    search_results: int = 10
    page_char_limit: int = 6000
    max_field_chars: int = 200
    http_timeout_seconds: int = 20

    # Paths
    outputs_dir: Path = field(default_factory=lambda: Path(os.getenv("OUTPUTS_DIR") or ROOT / "outputs"))
    cache_dir: Path = ROOT / ".cache"
    logs_dir: Path = ROOT / "logs"
    data_dir: Path = ROOT / "data"
    samples_dir: Path = ROOT / "docs" / "samples"

    def model_for_stage(self, stage: int) -> str:
        """Stages 1-2 use the default model; stages 3-4 use the strategy model."""
        return self.model_strategy if stage >= 3 else self.model_default

    def missing_keys(self) -> list[str]:
        missing = []
        if not self.openai_api_key or self.openai_api_key.startswith("your-"):
            missing.append("OPENAI_API_KEY")
        if not (self.serpapi_api_key or self.serper_api_key):
            missing.append("SERPAPI_API_KEY or SERPER_API_KEY")
        return missing


settings = Settings()
