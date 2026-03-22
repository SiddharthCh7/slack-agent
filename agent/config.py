"""
Configuration for the Slack Community Agent.

Company-specific content lives in config/ at the project root:
  config/agent.yaml  — agent persona (name, company name, voice)
  config/about.md    — company/product description injected into LLM prompts
  config/repos.md    — repo descriptions injected into the researcher prompt
  config/team.json   — org-member list for bot-silence detection
  config/repos.yaml  — GitHub repos to clone for codebase search
"""

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"


def _optional_stripped_env(name: str) -> Optional[str]:
    v = (os.getenv(name) or "").strip()
    return v if v else None


def _load_text(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return fallback


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Company / persona — loaded once at import time from config/agent.yaml
# ─────────────────────────────────────────────────────────────────────────────

_agent_cfg = _load_yaml(_CONFIG_DIR / "agent.yaml")

AGENT_NAME: str = os.getenv("AGENT_NAME") or _agent_cfg.get("agent_name", "Alex")
COMPANY_NAME: str = os.getenv("COMPANY_NAME") or _agent_cfg.get("company_name", "the company")
COMPANY_VOICE: str = _agent_cfg.get(
    "company_voice",
    f"Speak as part of {COMPANY_NAME}: use 'we' and 'our', never 'they' or 'their'.",
)

# ─────────────────────────────────────────────────────────────────────────────
# Company knowledge — loaded from config/*.md
# ─────────────────────────────────────────────────────────────────────────────

ABOUT_COMPANY: str = _load_text(_CONFIG_DIR / "about.md")
ABOUT_REPOS: str = _load_text(_CONFIG_DIR / "repos.md")


# ─────────────────────────────────────────────────────────────────────────────
# Runtime configuration
# ─────────────────────────────────────────────────────────────────────────────

class Config:
    """Runtime configuration — all values read from environment variables."""

    # LLM Provider
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-5")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "lfm2.5-thinking:latest")

    # Slack
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_APP_ID: str = os.getenv("SLACK_APP_ID", "")
    SLACK_CLIENT_ID: str = os.getenv("SLACK_CLIENT_ID", "")
    SLACK_CLIENT_SECRET: str = os.getenv("SLACK_CLIENT_SECRET", "")

    # Agent Behavior
    MAX_REASONING_ITERATIONS: int = int(os.getenv("MAX_REASONING_ITERATIONS", "5"))
    ENABLE_DEEP_REASONING: bool = os.getenv("ENABLE_DEEP_REASONING", "true").lower() == "true"

    # Database — SQLite file (default) or PostgreSQL when DATABASE_URL is set (Docker / hosted)
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/slack_agent.db")
    DATABASE_URL: Optional[str] = _optional_stripped_env("DATABASE_URL")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")

    # Server
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8001"))
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/slack/events")

    # Channel Configuration
    IGNORED_CHANNELS: list = [
        c.strip() for c in os.getenv("IGNORED_CHANNELS", "").split(",") if c.strip()
    ]
    HIGH_PRIORITY_CHANNELS: list = [
        c.strip() for c in os.getenv("HIGH_PRIORITY_CHANNELS", "").split(",") if c.strip()
    ]

    # Config file paths
    TEAM_FILE: Path = _CONFIG_DIR / "team.json"
    REPOS_CONFIG: Path = _CONFIG_DIR / "repos.yaml"
    TERMINAL_TOOL_CONFIG: Path = _CONFIG_DIR / "terminal_allowed_commands.yaml"

    # LLM request timeout
    LLM_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "200"))

    # Deep Research Agent
    MAX_RESEARCH_ITERATIONS: int = int(os.getenv("MAX_RESEARCH_ITERATIONS", "20"))
    MAX_CONTEXT_FILES: int = int(os.getenv("MAX_CONTEXT_FILES", "15"))
    RESEARCH_TIMEOUT_SECONDS: int = int(os.getenv("RESEARCH_TIMEOUT_SECONDS", "120"))

    @classmethod
    def validate(cls) -> bool:
        errors = []

        if not cls.SLACK_BOT_TOKEN:
            errors.append("SLACK_BOT_TOKEN is required")

        if not cls.SLACK_SIGNING_SECRET:
            errors.append("SLACK_SIGNING_SECRET is required")

        if cls.LLM_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is required when using OpenAI")

        if cls.LLM_PROVIDER == "gemini" and not cls.GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY is required when using Gemini")

        if cls.LLM_PROVIDER == "openrouter" and not cls.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY is required when using OpenRouter")

        if errors:
            for error in errors:
                print(f"Configuration Error: {error}")
            return False

        return True

    @classmethod
    def print_config(cls) -> None:
        def mask(value: str) -> str:
            if not value or len(value) < 8:
                return "***"
            return f"{value[:4]}...{value[-4:]}"

        print(f"\nSlack Community Agent — {COMPANY_NAME}")
        print("=" * 50)
        print(f"Agent name:   {AGENT_NAME}")
        print(f"Company:      {COMPANY_NAME}")
        print(f"LLM Provider: {cls.LLM_PROVIDER}")
        print(f"Slack Token:  {mask(cls.SLACK_BOT_TOKEN)}")
        if cls.DATABASE_URL:
            parsed = urlparse(cls.DATABASE_URL)
            host = parsed.hostname or "?"
            db = (parsed.path or "/").strip("/") or "?"
            print(f"Database:     PostgreSQL ({host}/{db})")
        else:
            print(f"Database:     SQLite ({cls.DATABASE_PATH})")
        print(f"Webhook Port: {cls.WEBHOOK_PORT}")
        print(f"Log Level:    {cls.LOG_LEVEL}")
        print("=" * 50 + "\n")


if __name__ == "__main__":
    Config.print_config()
    if Config.validate():
        print("Configuration is valid.")
    else:
        print("Configuration has errors.")
