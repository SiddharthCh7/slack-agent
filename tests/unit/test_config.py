#!/usr/bin/env python3
"""
Config Unit Tests with CLI Output

Usage:
    python -m tests.unit.test_config                # Run all tests
    python -m tests.unit.test_config --show         # Show all config values
    python -m tests.unit.test_config --validate     # Validate configuration
    python -m tests.unit.test_config --env          # Check environment variables
"""

import sys
import os
from pathlib import Path
from typing import Any, Dict

# Add paths for imports - works from project root or tests directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
RAG_PATH = PROJECT_ROOT / "services" / "rag"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(RAG_PATH))

from config import Config


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title: str) -> None:
    """Print a formatted section title."""
    print(f"\n--- {title} ---")


def print_config_table(config_dict: Dict[str, Any]) -> None:
    """Print configuration as a formatted table."""
    # Find max key length
    max_key = max(len(k) for k in config_dict.keys()) if config_dict else 0
    
    for key, value in sorted(config_dict.items()):
        # Mask sensitive values
        display_value = value
        if 'key' in key.lower() or 'token' in key.lower() or 'password' in key.lower():
            if value and len(value) > 4:
                display_value = value[:2] + '*' * (len(value) - 4) + value[-2:]
            elif value:
                display_value = '*' * len(value)
        
        print(f"  {key:<{max_key}}  {display_value}")


def test_show_config() -> None:
    """Show all configuration values."""
    print_header("CONFIGURATION VALUES")
    
    config_dict = {
        # Qdrant
        "QDRANT_URL": Config.QDRANT_URL,
        "QDRANT_API_KEY": Config.QDRANT_API_KEY,
        "DOCS_COLLECTION": Config.DOCS_COLLECTION,
        "CODE_COLLECTION": Config.CODE_COLLECTION,
        
        # Embedding
        "EMBED_MODEL": Config.EMBED_MODEL,
        "EMBED_BATCH_SIZE": Config.EMBED_BATCH_SIZE,
        "EMBED_DEVICE": Config.EMBED_DEVICE,
        
        # Chunking
        "MAX_CHUNK_CHARS": Config.MAX_CHUNK_CHARS,
        "OVERLAP_CHARS": Config.OVERLAP_CHARS,
        
        # Retrieval
        "DOC_RELEVANCE_THRESHOLD": Config.DOC_RELEVANCE_THRESHOLD,
        "MAX_RETRIEVED_DOCS": Config.MAX_RETRIEVED_DOCS,
        "RRF_K": Config.RRF_K,
        
        # Server
        "HOST": Config.HOST,
        "PORT": Config.PORT,
        "LOG_LEVEL": Config.LOG_LEVEL,
    }
    
    print_section("Qdrant Configuration")
    qdrant_config = {k: v for k, v in config_dict.items() if 'QDRANT' in k or 'COLLECTION' in k}
    print_config_table(qdrant_config)
    
    print_section("Embedding Configuration")
    embed_config = {k: v for k, v in config_dict.items() if 'EMBED' in k}
    print_config_table(embed_config)
    
    print_section("Chunking Configuration")
    chunk_config = {k: v for k, v in config_dict.items() if 'CHUNK' in k or 'OVERLAP' in k}
    print_config_table(chunk_config)
    
    print_section("Retrieval Configuration")
    retrieval_config = {k: v for k, v in config_dict.items() 
                       if 'THRESHOLD' in k or 'RETRIEVED' in k or 'RRF' in k}
    print_config_table(retrieval_config)
    
    print_section("Server Configuration")
    server_config = {k: v for k, v in config_dict.items() 
                    if k in ['HOST', 'PORT', 'LOG_LEVEL']}
    print_config_table(server_config)


def test_validate_config() -> bool:
    """Validate configuration values."""
    print_header("CONFIGURATION VALIDATION")
    
    errors = []
    warnings = []
    
    print_section("Validating...")
    
    # Qdrant URL
    if not Config.QDRANT_URL:
        errors.append("QDRANT_URL is not set")
    elif Config.QDRANT_URL.startswith("http") and not Config.QDRANT_API_KEY:
        warnings.append("Qdrant Cloud URL set but QDRANT_API_KEY is empty")
    
    # Collections
    if not Config.DOCS_COLLECTION:
        errors.append("DOCS_COLLECTION is not set")
    if not Config.CODE_COLLECTION:
        errors.append("CODE_COLLECTION is not set")
    if Config.DOCS_COLLECTION == Config.CODE_COLLECTION:
        warnings.append("DOCS_COLLECTION and CODE_COLLECTION are the same")
    
    # Embedding
    if not Config.EMBED_MODEL:
        errors.append("EMBED_MODEL is not set")
    if Config.EMBED_BATCH_SIZE <= 0:
        errors.append("EMBED_BATCH_SIZE must be positive")
    
    # Chunking
    if Config.MAX_CHUNK_CHARS <= 0:
        errors.append("MAX_CHUNK_CHARS must be positive")
    if Config.OVERLAP_CHARS < 0:
        errors.append("OVERLAP_CHARS cannot be negative")
    if Config.OVERLAP_CHARS >= Config.MAX_CHUNK_CHARS:
        warnings.append("OVERLAP_CHARS is close to MAX_CHUNK_CHARS")
    
    # Retrieval
    if not (0 <= Config.DOC_RELEVANCE_THRESHOLD <= 1):
        errors.append("DOC_RELEVANCE_THRESHOLD must be between 0 and 1")
    if Config.MAX_RETRIEVED_DOCS <= 0:
        errors.append("MAX_RETRIEVED_DOCS must be positive")
    if Config.RRF_K <= 0:
        errors.append("RRF_K must be positive")
    
    # Server
    if not Config.HOST:
        errors.append("HOST is not set")
    if not (0 < Config.PORT <= 65535):
        errors.append("PORT must be between 1 and 65535")
    
    # Print results
    if errors:
        print("\n  ERRORS:")
        for error in errors:
            print(f"    ✗ {error}")
    
    if warnings:
        print("\n  WARNINGS:")
        for warning in warnings:
            print(f"    ⚠ {warning}")
    
    if not errors and not warnings:
        print("\n  ✓ All configuration values are valid")
        return True
    elif not errors:
        print("\n  ✓ Configuration is valid (with warnings)")
        return True
    else:
        print(f"\n  ✗ Configuration has {len(errors)} error(s)")
        return False


def test_env_variables() -> None:
    """Check environment variable overrides."""
    print_header("ENVIRONMENT VARIABLES")
    
    env_vars = {
        "QDRANT_URL": os.getenv("QDRANT_URL"),
        "QDRANT_API_KEY": os.getenv("QDRANT_API_KEY"),
        "DOCS_COLLECTION": os.getenv("DOCS_COLLECTION"),
        "CODE_COLLECTION": os.getenv("CODE_COLLECTION"),
        "EMBED_MODEL": os.getenv("EMBED_MODEL"),
        "EMBED_BATCH_SIZE": os.getenv("EMBED_BATCH_SIZE"),
        "EMBED_DEVICE": os.getenv("EMBED_DEVICE"),
        "MAX_CHUNK_CHARS": os.getenv("MAX_CHUNK_CHARS"),
        "OVERLAP_CHARS": os.getenv("OVERLAP_CHARS"),
        "DOC_RELEVANCE_THRESHOLD": os.getenv("DOC_RELEVANCE_THRESHOLD"),
        "MAX_RETRIEVED_DOCS": os.getenv("MAX_RETRIEVED_DOCS"),
        "RAG_HOST": os.getenv("RAG_HOST"),
        "RAG_PORT": os.getenv("RAG_PORT"),
        "LOG_LEVEL": os.getenv("LOG_LEVEL"),
    }
    
    print_section("Environment Variables")
    
    set_vars = {k: v for k, v in env_vars.items() if v is not None}
    unset_vars = {k: v for k, v in env_vars.items() if v is None}
    
    if set_vars:
        print(f"\n  Set ({len(set_vars)}):")
        for key, value in sorted(set_vars.items()):
            # Mask sensitive values
            if 'key' in key.lower() or 'token' in key.lower():
                display = value[:2] + '*' * (len(value) - 4) + value[-2:] if len(value) > 4 else '*' * len(value)
            else:
                display = value
            print(f"    {key}={display}")
    
    if unset_vars:
        print(f"\n  Not Set ({len(unset_vars)}):")
        for key in sorted(unset_vars.keys()):
            print(f"    {key}=(default will be used)")
    
    print_section("Defaults Used")
    defaults_used = []
    
    if not os.getenv("QDRANT_URL"):
        defaults_used.append(f"QDRANT_URL={Config.QDRANT_URL}")
    if not os.getenv("DOCS_COLLECTION"):
        defaults_used.append(f"DOCS_COLLECTION={Config.DOCS_COLLECTION}")
    if not os.getenv("EMBED_MODEL"):
        defaults_used.append(f"EMBED_MODEL={Config.EMBED_MODEL}")
    if not os.getenv("OVERLAP_CHARS"):
        defaults_used.append(f"OVERLAP_CHARS={Config.OVERLAP_CHARS}")
    
    if defaults_used:
        for default in defaults_used:
            print(f"  {default}")
    else:
        print("  All values overridden by environment")


def test_chunking_config() -> None:
    """Test chunking-specific configuration."""
    print_header("CHUNKING CONFIGURATION TEST")
    
    print_section("Current Settings")
    print(f"\n  MAX_CHUNK_CHARS:  {Config.MAX_CHUNK_CHARS}")
    print(f"  OVERLAP_CHARS:    {Config.OVERLAP_CHARS}")
    print(f"  Overlap Ratio:    {100 * Config.OVERLAP_CHARS / Config.MAX_CHUNK_CHARS:.1f}%")
    
    print_section("Validation")
    
    # Check overlap is reasonable
    overlap_ratio = Config.OVERLAP_CHARS / Config.MAX_CHUNK_CHARS
    
    if overlap_ratio < 0.05:
        print(f"\n  ⚠ Overlap ratio is very low ({overlap_ratio:.1%})")
        print(f"    Consider increasing OVERLAP_CHARS for better context")
    elif overlap_ratio > 0.5:
        print(f"\n  ⚠ Overlap ratio is very high ({overlap_ratio:.1%})")
        print(f"    Consider decreasing OVERLAP_CHARS to reduce redundancy")
    else:
        print(f"\n  ✓ Overlap ratio is reasonable ({overlap_ratio:.1%})")
    
    # Check token approximation
    # ~4 chars per token is a rough estimate
    estimated_tokens = Config.OVERLAP_CHARS / 4
    print(f"\n  Estimated overlap: ~{estimated_tokens:.0f} tokens")
    
    if 80 <= estimated_tokens <= 120:
        print(f"  ✓ Overlap is approximately 100 tokens as intended")
    else:
        print(f"  ⚠ Overlap may differ from intended ~100 tokens")


def test_retrieval_config() -> None:
    """Test retrieval-specific configuration."""
    print_header("RETRIEVAL CONFIGURATION TEST")
    
    print_section("Current Settings")
    print(f"\n  DOC_RELEVANCE_THRESHOLD:  {Config.DOC_RELEVANCE_THRESHOLD}")
    print(f"  MAX_RETRIEVED_DOCS:       {Config.MAX_RETRIEVED_DOCS}")
    print(f"  RRF_K:                    {Config.RRF_K}")
    
    print_section("Threshold Analysis")
    
    threshold = Config.DOC_RELEVANCE_THRESHOLD
    
    if threshold < 0.2:
        print(f"\n  ⚠ Low threshold ({threshold})")
        print(f"    May return many low-quality results")
    elif threshold > 0.7:
        print(f"\n  ⚠ High threshold ({threshold})")
        print(f"    May filter out relevant results")
    else:
        print(f"\n  ✓ Threshold ({threshold}) is in typical range")
    
    print_section("RRF Configuration")
    print(f"\n  RRF_K = {Config.RRF_K}")
    print(f"  Purpose: Controls ranking fusion in hybrid search")
    print(f"  Typical range: 10-100")
    
    if 10 <= Config.RRF_K <= 100:
        print(f"  ✓ RRF_K is in typical range")
    else:
        print(f"  ⚠ RRF_K outside typical range")


def run_all_tests() -> None:
    """Run all config tests."""
    print_header("CONFIG UNIT TESTS")
    
    test_show_config()
    test_validate_config()
    test_env_variables()
    test_chunking_config()
    test_retrieval_config()
    
    print_header("ALL TESTS COMPLETE")
    print("\n  All config tests finished.\n")


def main():
    """Main entry point with CLI argument handling."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Config Unit Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.unit.test_config                # Run all tests
  python -m tests.unit.test_config --show         # Show all config values
  python -m tests.unit.test_config --validate     # Validate configuration
  python -m tests.unit.test_config --env          # Check environment variables
        """
    )
    
    parser.add_argument("--show", action="store_true", 
                        help="Show all configuration values")
    parser.add_argument("--validate", action="store_true", 
                        help="Validate configuration")
    parser.add_argument("--env", action="store_true", 
                        help="Check environment variables")
    parser.add_argument("--chunking", action="store_true", 
                        help="Test chunking configuration")
    parser.add_argument("--retrieval", action="store_true", 
                        help="Test retrieval configuration")
    
    args = parser.parse_args()
    
    # Change to project root
    os.chdir(Path(__file__).parent.parent.parent)
    
    # Run specific tests based on arguments
    if args.show:
        test_show_config()
    elif args.validate:
        test_validate_config()
    elif args.env:
        test_env_variables()
    elif args.chunking:
        test_chunking_config()
    elif args.retrieval:
        test_retrieval_config()
    else:
        # No specific test requested, run all
        run_all_tests()


if __name__ == "__main__":
    main()
