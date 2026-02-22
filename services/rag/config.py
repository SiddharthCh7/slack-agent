"""
RAG Service Configuration.

All settings resolved from environment variables.
Qdrant URL supports:
  - ./qdrant_db           → local file persistence (dev)
  - http://qdrant:6333    → Docker Compose
  - https://xyz.cloud.qdrant.io → Qdrant Cloud (set QDRANT_API_KEY too)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (parent of services/rag)
# override=True to ensure .env values take precedence over shell env vars
project_root = Path(__file__).parent.parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)  # Fallback to current directory


class Config:
    # ── Qdrant ────────────────────────────────────────────────────────────
    QDRANT_URL: str = os.getenv("QDRANT_URL", "./qdrant_db")
    QDRANT_API_KEY: str | None = os.getenv("QDRANT_API_KEY")   # required for Qdrant Cloud

    DOCS_COLLECTION: str = os.getenv("DOCS_COLLECTION", "olake_docs")
    CODE_COLLECTION: str = os.getenv("CODE_COLLECTION", "olake_code")

    # ── Embedding ─────────────────────────────────────────────────────────
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
    EMBED_BATCH_SIZE: int = int(os.getenv("EMBED_BATCH_SIZE", "64"))
    EMBED_DEVICE: str = os.getenv("EMBED_DEVICE", "cpu")   # "cuda" on GPU hosts

    # ── Chunking ──────────────────────────────────────────────────────────
    MAX_CHUNK_CHARS: int = int(os.getenv("MAX_CHUNK_CHARS", "2500"))
    OVERLAP_CHARS: int = int(os.getenv("OVERLAP_CHARS", "400"))  # ~100 tokens

    # ── Retrieval ─────────────────────────────────────────────────────────
    DOC_RELEVANCE_THRESHOLD: float = float(os.getenv("DOC_RELEVANCE_THRESHOLD", "0.35"))
    MAX_RETRIEVED_DOCS: int = int(os.getenv("MAX_RETRIEVED_DOCS", "6"))
    RRF_K: int = int(os.getenv("RRF_K", "10"))

    # ── Docs source ───────────────────────────────────────────────────────
    DOCS_FILE: Path = Path(os.getenv("DOCS_FILE", "./docs/olake_docs.md"))

    # ── Server ────────────────────────────────────────────────────────────
    HOST: str = os.getenv("RAG_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("RAG_PORT", "7070"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
