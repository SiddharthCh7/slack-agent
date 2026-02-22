"""
Enhanced configuration for OLake Slack Community Agent.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Path to team definition file (relative to project root)
TEAM_FILE_PATH = Path(__file__).parent.parent / "olake-team.json"


class Config:
    """Configuration for Slack Community Agent."""
    
    # LLM Provider
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    
    # Slack
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_APP_ID: str = os.getenv("SLACK_APP_ID", "")
    SLACK_CLIENT_ID: str = os.getenv("SLACK_CLIENT_ID", "")
    SLACK_CLIENT_SECRET: str = os.getenv("SLACK_CLIENT_SECRET", "")
    
    # Agent Behavior
    MAX_REASONING_ITERATIONS: int = int(os.getenv("MAX_REASONING_ITERATIONS", "5"))
    CONFIDENCE_THRESHOLD_FOR_AUTO_REPLY: float = float(
        os.getenv("CONFIDENCE_THRESHOLD_FOR_AUTO_REPLY", "0.75")
    )
    ENABLE_DEEP_REASONING: bool = os.getenv("ENABLE_DEEP_REASONING", "true").lower() == "true"
    ENABLE_USER_LEARNING: bool = os.getenv("ENABLE_USER_LEARNING", "true").lower() == "true"
    MAX_CONTEXT_MESSAGES: int = int(os.getenv("MAX_CONTEXT_MESSAGES", "10"))
    
    # Documentation Search
    ENABLE_VECTOR_SEARCH: bool = os.getenv("ENABLE_VECTOR_SEARCH", "false").lower() == "true"
    MAX_RETRIEVED_DOCS: int = int(os.getenv("MAX_RETRIEVED_DOCS", "5"))
    DOC_RELEVANCE_THRESHOLD: float = float(os.getenv("DOC_RELEVANCE_THRESHOLD", "0.6"))
    # Threshold above which retrieved docs are considered sufficient to answer the question
    DOCS_ANSWER_THRESHOLD: float = float(os.getenv("DOCS_ANSWER_THRESHOLD", "0.5"))
    DOCS_PATH: str = os.getenv("DOCS_PATH", "docs/olake_knowledge_base")

    # Vector DB — Chroma / Qdrant
    VECTOR_DB_URL: str = os.getenv("VECTOR_DB_URL", "./qdrant_db")
    DOCS_COLLECTION: str = os.getenv("DOCS_COLLECTION", "olake_docs")
    CODE_COLLECTION: str = os.getenv("CODE_COLLECTION", "olake_code")
    
    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/slack_agent.db")
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")
    
    # Server
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "3000"))
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/slack/events")
    
    # Channel Configuration (Optional)
    IGNORED_CHANNELS: list = [
        c.strip() for c in os.getenv("IGNORED_CHANNELS", "").split(",") if c.strip()
    ]
    HIGH_PRIORITY_CHANNELS: list = [
        c.strip() for c in os.getenv("HIGH_PRIORITY_CHANNELS", "").split(",") if c.strip()
    ]

    # Team / Escalation — loaded from olake-team.json (no env var needed)
    # Org member detection uses slack_name matching via team_resolver.py
    TEAM_FILE: Path = Path(__file__).parent.parent / "olake-team.json"
    
    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration."""
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
                print(f"❌ Configuration Error: {error}")
            return False
        
        return True
    
    @classmethod
    def print_config(cls) -> None:
        """Print current configuration (sanitized)."""
        def mask_secret(value: str) -> str:
            if not value or len(value) < 8:
                return "***"
            return f"{value[:4]}...{value[-4:]}"
        
        print("\n📋 OLake Slack Agent Configuration")
        print("=" * 50)
        print(f"LLM Provider: {cls.LLM_PROVIDER}")
        print(f"Slack Bot Token: {mask_secret(cls.SLACK_BOT_TOKEN)}")
        print(f"Max Reasoning Iterations: {cls.MAX_REASONING_ITERATIONS}")
        print(f"Confidence Threshold: {cls.CONFIDENCE_THRESHOLD_FOR_AUTO_REPLY}")
        print(f"Deep Reasoning Enabled: {cls.ENABLE_DEEP_REASONING}")
        print(f"User Learning Enabled: {cls.ENABLE_USER_LEARNING}")
        print(f"Vector Search Enabled: {cls.ENABLE_VECTOR_SEARCH}")
        print(f"Database Path: {cls.DATABASE_PATH}")
        print(f"Webhook Port: {cls.WEBHOOK_PORT}")
        print(f"Log Level: {cls.LOG_LEVEL}")
        print("=" * 50 + "\n")


# OLake Context (for LLM)
OLAKE_CONTEXT = """
OLake is an open-source data ingestion tool from databases to Apache Iceberg. It helps organizations build reliable, scalable data pipelines with support 
for Apache Iceberg, CDC (Change Data Capture), and various data sources.

Key Features:
- Easy CDC pipelines from databases to Apache Iceberg tables
- Support for multiple data sources (PostgreSQL, MySQL, MongoDB, etc.)
- Built-in schema evolution and data quality checks
- Cost-effective with optimized storage patterns
- Open-source and community-driven

Common Use Cases:
- Real-time data replication
- Data warehouse modernization
- Building data lakehouses
- ETL/ELT workflows

Documentation: https://olake.io/docs/
GitHub: https://github.com/datazip-inc/olake
"""


def load_olake_docs() -> str:
    """Load OLake documentation from files."""
    docs_path = Path(Config.DOCS_PATH)
    
    if not docs_path.exists():
        # Fallback to about_olake.md
        about_path = Path("docs/about_olake.md")
        if about_path.exists():
            return about_path.read_text()
        return OLAKE_CONTEXT
    
    # If we have a knowledge base directory, load all markdown files
    all_docs = []
    for md_file in docs_path.rglob("*.md"):
        try:
            all_docs.append(f"\n\n# {md_file.stem}\n{md_file.read_text()}")
        except Exception:
            continue
    
    return "\n".join(all_docs) if all_docs else OLAKE_CONTEXT


# Validate on import
if __name__ == "__main__":
    Config.print_config()
    if Config.validate():
        print("✅ Configuration is valid!")
    else:
        print("❌ Configuration has errors!")
